#!/usr/bin/env python3
import argparse
import codecs
import kdtree
import logging
import math
import requests
import os
import sys
from io import BytesIO
from .version import __version__
import json    # for profiles
import re      # for profiles
import zipfile # for profiles
try:
    from lxml import etree
except ImportError:
    import xml.etree.ElementTree as etree

TITLE = 'OSM Conflator ' + __version__
OVERPASS_SERVER = 'http://overpass-api.de/api/'
BBOX_PADDING = 0.003  # in degrees, ~330 m default
MAX_DISTANCE = 100  # how far can object be to be considered a match, in meters


class SourcePoint:
    """A common class for points. Has an id, latitude and longitude,
    and a dict of tags."""
    def __init__(self, pid, lat, lon, tags=None):
        self.id = str(pid)
        self.lat = lat
        self.lon = lon
        self.tags = {} if tags is None else {k.lower(): str(v) for k, v in tags.items()}
        self.dist_offset = 0

    def distance(self, other):
        """Calculate distance in meters."""
        dx = math.radians(self.lon - other.lon) * math.cos(0.5 * math.radians(self.lat + other.lat))
        dy = math.radians(self.lat - other.lat)
        return 6378137 * math.sqrt(dx*dx + dy*dy) - self.dist_offset

    def __len__(self):
        return 2

    def __getitem__(self, i):
        if i == 0:
            return self.lat
        elif i == 1:
            return self.lon
        else:
            raise ValueError('A SourcePoint has only lat and lon in a list')

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return 'SourcePoint({}, {}, {}, offset={}, tags={})'.format(
            self.id, self.lat, self.lon, self.dist_offset, self.tags)


class OSMPoint(SourcePoint):
    """An OSM points is a SourcePoint with a few extra fields.
    Namely, version, members (for ways and relations), and an action.
    The id is compound and created from object type and object id."""
    def __init__(self, ptype, pid, version, lat, lon, tags=None):
        super().__init__('{}{}'.format(ptype[0], pid), lat, lon, tags)
        self.osm_type = ptype
        self.osm_id = pid
        self.version = version
        self.members = None
        self.action = None

    def copy(self):
        """Returns a copy of this object, except for members field."""
        c = OSMPoint(self.osm_type, self.osm_id, self.version, self.lat, self.lon, self.tags.copy())
        c.action = self.action
        return c

    def is_area(self):
        return self.osm_type != 'node'

    def is_poi(self):
        if self.osm_type == 'node':
            return True
        if self.osm_type == 'way' and len(self.members) > 2:
            return self.members[0] == self.members[-1]
        if self.osm_type == 'relation' and len(self.members) > 0:
            return self.tags.get('type', None) == 'multipolygon'
        return False

    def to_xml(self):
        """Produces an XML out of the point data. Disregards the "action" field."""
        el = etree.Element(self.osm_type, id=str(self.osm_id), version=str(self.version))
        for tag, value in self.tags.items():
            etree.SubElement(el, 'tag', k=tag, v=value)

        if self.osm_type == 'node':
            el.set('lat', str(self.lat))
            el.set('lon', str(self.lon))
        elif self.osm_type == 'way':
            for node_id in self.members:
                etree.SubElement(el, 'nd', ref=str(node_id))
        elif self.osm_type == 'relation':
            for member in self.members:
                m = etree.SubElement(el, 'member')
                for i, n in enumerate(('type', 'ref', 'role')):
                    m.set(n, str(member[i]))
        return el

    def __repr__(self):
        return 'OSMPoint({} {} v{}, {}, {}, action={}, tags={})'.format(
            self.osm_type, self.osm_id, self.version, self.lat, self.lon, self.action, self.tags)


class ProfileException(Exception):
    """An exception class for the Profile instance."""
    def __init__(self, attr, desc):
        super().__init__('Field missing in profile: {} ({})'.format(attr, desc))


class Profile:
    """A wrapper for a profile.

    A profile is a python script that sets a few local variables.
    These variables become properties of the profile, accessible with
    a "get" method. If something is a function, it will be called,
    optional parameters might be passed to it.

    You can compile a list of all supported variables by grepping through
    this code, or by looking at a few example profiles. If something
    is required, you will be notified of that.
    """
    def __init__(self, fileobj):
        if isinstance(fileobj, dict):
            self.profile = fileobj
        elif hasattr(fileobj, 'read'):
            s = fileobj.read().replace('\r', '')
            if s[0] == '{':
                self.profile = json.loads(s)
            else:
                self.profile = {}
                exec(s, globals(), self.profile)
        else:
            # Got a class
            self.profile = {name: getattr(fileobj, name)
                            for name in dir(fileobj) if not name.startswith('_')}

    def has(self, attr):
        return attr in self.profile

    def get(self, attr, default=None, required=None, args=None):
        if attr in self.profile:
            value = self.profile[attr]
            if callable(value):
                if args is None:
                    return value()
                else:
                    return value(*args)
            else:
                return value
        if required is not None:
            raise ProfileException(attr, required)
        return default

    def get_raw(self, attr, default=None):
        if attr in self.profile:
            return self.profile[attr]
        return default


class OsmConflator:
    """The main class for the conflator.

    It receives a dataset, after which one must call either
    "download_osm" or "parse_osm" methods. Then it is ready to match:
    call the "match" method and get results with "to_osc".
    """
    def __init__(self, profile, dataset):
        self.dataset = {p.id: p for p in dataset}
        self.osmdata = {}
        self.matched = []
        self.changes = []
        self.profile = profile
        self.source = self.profile.get('source', required='value of "source" tag for uploaded OSM objects')
        self.add_source_tag = self.profile.get('add_source', False)
        if self.profile.get('no_dataset_id', False):
            self.ref = None
        else:
            self.ref = 'ref:' + self.profile.get('dataset_id', required='A fairly unique id of the dataset to query OSM')

    def construct_overpass_query(self, bboxes=None):
        """Constructs an Overpass API query from the "query" list in the profile.
        (k, v) turns into [k=v], (k,) into [k], (k, None) into [!k], (k, "~v") into [k~v]."""
        tags = self.profile.get('query', required="a list of tuples. E.g. [('amenity', 'cafe'), ('name', '~Mc.*lds')]")
        if isinstance(tags, str):
            tag_str = tags
        else:
            tag_str = ''
            for t in tags:
                if len(t) == 1:
                    q = '"{}"'.format(t[0])
                elif t[1] is None or len(t[1]) == 0:
                    q = '"!{}"'.format(t[0])
                elif t[1][0] == '~':
                    q = '"{}"~"{}"'.format(t[0], t[1][1:])
                else:
                    q = '"{}"="{}"'.format(t[0], t[1])
                tag_str += '[' + q + ']'

        timeout = self.profile.get('overpass_timeout', 120)
        query = '[out:xml]{};('.format('' if timeout is None else '[timeout:{}]'.format(timeout))
        for bbox in bboxes:
            bbox_str = '' if bbox is None else '(' + ','.join([str(x) for x in bbox]) + ')'
            for t in ('node', 'way', 'relation["type"="multipolygon"]'):
                query += t + tag_str + bbox_str + ';'
        if self.ref is not None:
            for t in ('node', 'way', 'relation'):
                query += t + '["' + self.ref + '"];'
        query += '); out meta qt center;'
        return query

    def get_dataset_bbox(self):
        """Plain iterates over the dataset and returns the bounding box
        that encloses it."""
        padding = self.profile.get('bbox_padding', BBOX_PADDING)
        bbox = [90.0, 180.0, -90.0, -180.0]
        for p in self.dataset.values():
            bbox[0] = min(bbox[0], p.lat - padding)
            bbox[1] = min(bbox[1], p.lon - padding)
            bbox[2] = max(bbox[2], p.lat + padding)
            bbox[3] = max(bbox[3], p.lon + padding)
        return bbox

    def split_into_bboxes(self):
        """
        Splits the dataset into multiple bboxes to lower load on the overpass api.

        Returns a list of tuples (minlat, minlon, maxlat, maxlon).
        """
        if len(self.dataset) <= 1:
            return [self.get_dataset_bbox()]

        # coord, alt coord, total w/h to the left/bottom, total w/h to the right/top
        lons = sorted([[d.lon, d.lat, 0, 0] for d in self.dataset.values()])
        lats = sorted([[d.lat, d.lon, 0, 0] for d in self.dataset.values()])

        def update_side_dimensions(ar):
            """For each point, calculates the maximum and
            minimum bound for all points left and right."""
            fwd_top = fwd_bottom = ar[0][1]
            back_top = back_bottom = ar[-1][1]
            for i in range(len(ar)):
                fwd_top = max(fwd_top, ar[i][1])
                fwd_bottom = min(fwd_bottom, ar[i][1])
                ar[i][2] = fwd_top - fwd_bottom
                back_top = max(back_top, ar[-i-1][1])
                back_bottom = min(back_bottom, ar[-i-1][1])
                ar[-i-1][3] = back_top - back_bottom

        def find_max_gap(ar, h):
            """Select an interval between points, which would give
            the maximum area if split there."""
            max_id = None
            max_gap = 0
            for i in range(len(ar) - 1):
                # "Extra" variables are for area to the left and right
                # that would be freed after splitting.
                extra_left = (ar[i][0]-ar[0][0]) * (h-ar[i][2])
                extra_right = (ar[-1][0]-ar[i+1][0]) * (h-ar[i+1][3])
                # Gap is the area of the column between points i and i+1
                # plus extra areas to the left and right.
                gap = (ar[i+1][0] - ar[i][0]) * h + extra_left + extra_right
                if gap > max_gap:
                    max_id = i
                    max_gap = gap
            return max_id, max_gap

        def get_bbox(b, pad=0):
            """Returns a list of [min_lat, min_lon, max_lat, max_lon] for a box."""
            return [b[2][0][0]-pad, b[3][0][0]-pad, b[2][-1][0]+pad, b[3][-1][0]+pad]

        def split(box, point_array, point_id):
            """Split the box over axis point_array at point point_id...point_id+1.
            Modifies the box in-place and returns a new box."""
            alt_array = 5 - point_array  # 3->2, 2->3
            points = box[point_array][point_id+1:]
            del box[point_array][point_id+1:]
            alt = {True: [], False: []}  # True means point is in new box
            for p in box[alt_array]:
                alt[(p[1], p[0]) >= (points[0][0], points[0][1])].append(p)

            new_box = [None] * 4
            new_box[point_array] = points
            new_box[alt_array] = alt[True]
            box[alt_array] = alt[False]
            for i in range(2):
                box[i] = box[i+2][-1][0] - box[i+2][0][0]
                new_box[i] = new_box[i+2][-1][0] - new_box[i+2][0][0]
            return new_box

        # height, width, lats, lons
        max_bboxes = self.profile.get('max_request_boxes', 8)
        boxes = [[lats[-1][0]-lats[0][0], lons[-1][0]-lons[0][0], lats, lons]]
        initial_area = boxes[0][0] * boxes[0][1]
        while len(boxes) < max_bboxes and len(boxes) <= len(self.dataset):
            candidate_box = None
            area = 0
            point_id = None
            point_array = None
            for box in boxes:
                for ar in (2, 3):
                    # Find a box and an axis for splitting that would decrease the area the most
                    update_side_dimensions(box[ar])
                    max_id, max_area = find_max_gap(box[ar], box[3-ar])
                    if max_area > area:
                        area = max_area
                        candidate_box = box
                        point_id = max_id
                        point_array = ar
            if area * 100 < initial_area:
                # Stop splitting when the area decrease is less than 1%
                break
            logging.debug('Splitting bbox %s at %s %s-%s; area decrease %s%%',
                          get_bbox(candidate_box),
                          'longs' if point_array == 3 else 'lats',
                          candidate_box[point_array][point_id][0],
                          candidate_box[point_array][point_id+1][0],
                          round(100*area/initial_area))
            boxes.append(split(candidate_box, point_array, point_id))

        padding = self.profile.get('bbox_padding', BBOX_PADDING)
        return [get_bbox(b, padding) for b in boxes]

    def check_against_profile_tags(self, tags):
        qualifies = self.profile.get('qualifies', args=tags)
        if qualifies is not None:
            return qualifies

        query = self.profile.get('query', None)
        if query is not None:
            for tag in query:
                if len(tag) >= 1:
                    if tag[0] not in tags:
                        return False
                    if len(tag) >= 2 and tag[1][0] != '~':
                        if tag[1] != tags[tag[0]]:
                            return False
        return True

    def download_osm(self):
        """Constructs an Overpass API query and requests objects
        to match from a server."""
        profile_bbox = self.profile.get('bbox', True)
        if not profile_bbox:
            bboxes = [None]
        elif hasattr(profile_bbox, '__len__') and len(profile_bbox) == 4:
            bboxes = [profile_bbox]
        else:
            bboxes = self.split_into_bboxes()

        query = self.construct_overpass_query(bboxes)
        logging.debug('Overpass query: %s', query)
        r = requests.get(OVERPASS_SERVER + 'interpreter', {'data': query})
        if r.status_code != 200:
            logging.error('Failed to download data from Overpass API: %s', r.status_code)
            if 'rate_limited' in r.text:
                r = requests.get(OVERPASS_SERVER + 'status')
                logging.warning('Seems like you are rate limited. API status:\n%s', r.text)
            else:
                logging.error('Error message: %s', r.text)
            raise IOError()
        self.parse_osm(r.content)

    def parse_osm(self, fileobj):
        """Parses an OSM XML file into the "osmdata" field. For ways and relations,
        finds the center. Drops objects that do not match the overpass query tags
        (see "check_against_profile_tags" method)."""
        if isinstance(fileobj, bytes):
            xml = etree.fromstring(fileobj)
        else:
            xml = etree.parse(fileobj).getroot()
        nodes = {}
        for nd in xml.findall('node'):
            nodes[nd.get('id')] = (float(nd.get('lat')), float(nd.get('lon')))
        ways = {}
        for way in xml.findall('way'):
            center = way.find('center')
            if center is not None:
                ways[way.get('id')] = [float(center.get('lat')), float(center.get('lon'))]
            else:
                logging.warning('Way %s does not have a center', way.get('id'))
                coord = [0, 0]
                count = 0
                for nd in way.findall('nd'):
                    if nd.get('id') in nodes:
                        count += 1
                        for i in range(len(coord)):
                            coord[i] += nodes[nd.get('ref')][i]
                ways[way.get('id')] = [coord[0] / count, coord[1] / count]

        # For calculating weight of OSM objects
        weight_fn = self.profile.get_raw('weight')
        max_distance = self.profile.get('max_distance', MAX_DISTANCE)

        for el in xml:
            tags = {}
            for tag in el.findall('tag'):
                tags[tag.get('k')] = tag.get('v')
            if not self.check_against_profile_tags(tags):
                continue

            if el.tag == 'node':
                coord = nodes[el.get('id')]
                members = None
            elif el.tag == 'way':
                coord = ways[el.get('id')]
                members = [nd.get('ref') for nd in el.findall('nd')]
            elif el.tag == 'relation':
                center = el.find('center')
                if center is not None:
                    coord = [float(center.get('lat')), float(center.get('lon'))]
                else:
                    coord = [0, 0]
                    count = 0
                    for m in el.findall('member'):
                        if m.get('type') == 'node' and m.get('ref') in nodes:
                            count += 1
                            for i in range(len(coord)):
                                coord[i] += nodes[m.get('ref')][i]
                        elif m.get('type') == 'way' and m.get('ref') in ways:
                            count += 1
                            for i in range(len(coord)):
                                coord[i] += ways[m.get('ref')][i]
                    coord = [coord[0] / count, coord[1] / count]
                members = [(m.get('type'), m.get('ref'), m.get('role')) for m in el.findall('member')]
            pt = OSMPoint(el.tag, int(el.get('id')), int(el.get('version')), coord[0], coord[1], tags)
            pt.members = members
            if pt.is_poi():
                if callable(weight_fn):
                    weight = weight_fn(pt)
                    if weight:
                        pt.dist_offset = weight if abs(weight) > 3 else weight * max_distance
                self.osmdata[pt.id] = pt

    def register_match(self, dataset_key, osmdata_key, keep=False, retag=None):
        """Registers a match between an OSM point and a dataset point.

        Merges tags from an OSM Point and a dataset point, and add the result to the self.matched list.
        If dataset_key is None, deletes or retags the OSM point.
        If osmdata_key is None, adds a new OSM point for the dataset point.
        """
        def update_tags(tags, source, master_tags=None):
            """Updates tags dictionary with tags from source, returns True is something was changed."""
            changed = False
            if source:
                for k, v in source.items():
                    if k not in tags or (p.tags[k] != v and (not master_tags or k in master_tags)):
                        if v is not None and len(v) > 0:
                            p.tags[k] = v
                            changed = True
                        elif k in p.tags:
                            del p.tags[k]
                            changed = True
            return changed

        def format_change(before, after, ref):
            geometry = {'type': 'Point', 'coordinates': [after.lon, after.lat]}
            props = {'osm_type': after.osm_type, 'osm_id': after.osm_id, 'action': after.action}
            if after.action in ('create', 'delete'):
                # Red if deleted, green if added
                props['marker-color'] = '#ff0000' if after.action == 'delete' else '#00dd00'
                for k, v in after.tags.items():
                    props['tags.{}'.format(k)] = v
            else:  # modified
                # Blue if updated from dataset, dark red if retagged, dark blue if moved
                props['marker-color'] = '#0000ee' if ref else '#660000'
                if ref:
                    props['ref_distance'] = round(10 * ref.distance(after)) / 10.0
                    props['ref_coords'] = [ref.lon, ref.lat]
                    if before.lon != after.lon or before.lat != after.lat:
                        # The object was moved
                        props['were_coords'] = [before.lon, before.lat]
                        props['ref_distance'] = round(10 * ref.distance(before)) / 10.0
                        props['marker-color'] = '#000066'
                    # Find tags that were superseeded by OSM tags
                    unused_tags = {}
                    for k, v in ref.tags.items():
                        if k not in after.tags or after.tags[k] != v:
                            unused_tags[k] = v
                    if unused_tags:
                        for k, v in unused_tags.items():
                            props['ref_unused_tags.{}'.format(k)] = v
                # Now compare old and new OSM tags
                for k in set(after.tags.keys()).union(set(before.tags.keys())):
                    v0 = before.tags.get(k, None)
                    v1 = after.tags.get(k, None)
                    if v0 == v1:
                        props['tags.{}'.format(k)] = v0
                    elif v0 is None:
                        props['tags_new.{}'.format(k)] = v1
                    elif v1 is None:
                        props['tags_deleted.{}'.format(k)] = v0
                    else:
                        props['tags_changed.{}'.format(k)] = '{} -> {}'.format(v0, v1)
            return {'type': 'Feature', 'geometry': geometry, 'properties': props}

        max_distance = self.profile.get('max_distance', MAX_DISTANCE)
        p = self.osmdata.pop(osmdata_key, None)
        p0 = None if p is None else p.copy()
        sp = self.dataset.pop(dataset_key, None)

        if sp is not None:
            if p is None:
                p = OSMPoint('node', -1-len(self.matched), 1, sp.lat, sp.lon, sp.tags)
                p.action = 'create'
            else:
                master_tags = set(self.profile.get('master_tags', required='a set of authoritative tags that replace OSM values'))
                if update_tags(p.tags, sp.tags, master_tags):
                    p.action = 'modify'
                # Move a node if it is too far from the dataset point
                if not p.is_area() and sp.distance(p) > max_distance:
                    p.lat = sp.lat
                    p.lon = sp.lon
                    p.action = 'modify'
            if self.add_source_tag:
                if 'source' in p.tags:
                    if self.source not in p.tags['source']:
                        p.tags['source'] = ';'.join([p.tags['source'], self.source])
                else:
                    p.tags['source'] = self.source
            if self.ref is not None:
                p.tags[self.ref] = sp.id
        elif keep or p.is_area():
            if update_tags(p.tags, retag):
                p.action = 'modify'
        else:
            p.action = 'delete'

        if p.action is not None:
            self.matched.append(p)
            self.changes.append(format_change(p0, p, sp))

    def match_dataset_points_smart(self):
        """Smart matching for dataset <-> OSM points.

        We find a shortest link between a dataset and an OSM point.
        Then we match these and remove both from dicts.
        Then find another link and so on, until the length of a link
        becomes larger than "max_distance".

        Currently the worst case complexity is around O(n^2*log^2 n).
        But given the small number of objects to match, and that
        the average case complexity is ~O(n*log^2 n), this is fine.
        """
        def search_nn_fix(kd, point):
            nearest = kd.search_knn(point, 10)
            if not nearest:
                return None, None
            nearest = [(n[0], n[0].data.distance(point)) for n in nearest]
            return sorted(nearest, key=lambda kv: kv[1])[0]

        if not self.osmdata:
            return
        max_distance = self.profile.get('max_distance', MAX_DISTANCE)
        osm_kd = kdtree.create(list(self.osmdata.values()))
        count_matched = 0
        dist = []
        for sp, v in self.dataset.items():
            osm_point, distance = search_nn_fix(osm_kd, v)
            if osm_point is not None and distance <= max_distance:
                dist.append((distance, sp, osm_point.data))
        needs_sorting = True
        while dist:
            if needs_sorting:
                dist.sort(key=lambda x: x[0])
                needs_sorting = False
            count_matched += 1
            osm_point = dist[0][2]
            self.register_match(dist[0][1], osm_point.id)
            osm_kd = osm_kd.remove(osm_point)
            del dist[0]
            for i in range(len(dist)-1, -1, -1):
                if dist[i][2] == osm_point:
                    nearest, distance = search_nn_fix(osm_kd, self.dataset[dist[i][1]])
                    if nearest and distance <= max_distance:
                        dist[i] = (distance, dist[i][1], nearest.data)
                        needs_sorting = i == 0 or distance < dist[0][0]
                    else:
                        del dist[i]
                        needs_sorting = i == 0
        logging.info('Matched %s points', count_matched)

    def match(self):
        """Matches each osm object with a SourcePoint, or marks it as obsolete.
        The resulting list of OSM Points are written to the "matched" field."""
        if self.ref is not None:
            # First match all objects with ref:whatever tag set
            count_ref = 0
            for k, p in list(self.osmdata.items()):
                if self.ref in p.tags:
                    if p.tags[self.ref] in self.dataset:
                        count_ref += 1
                        self.register_match(p.tags[self.ref], k)
            logging.info('Updated %s OSM objects with %s tag', count_ref, self.ref)

        # Then find matches for unmatched dataset points
        self.match_dataset_points_smart()

        # Add unmatched dataset points
        logging.info('Adding %s unmatched dataset points', len(self.dataset))
        for k in sorted(list(self.dataset.keys())):
            self.register_match(k, None)

        # And finally delete some or all of the remaining osm objects
        if len(self.osmdata) > 0:
            count_deleted = 0
            count_retagged = 0
            delete_unmatched = self.profile.get('delete_unmatched', False)
            retag = self.profile.get('tag_unmatched')
            for k, p in list(self.osmdata.items()):
                if self.ref is not None and self.ref in p.tags:
                    # When ref:whatever is present, we can delete that object safely
                    count_deleted += 1
                    self.register_match(None, k, retag=retag)
                elif delete_unmatched or retag:
                    if not delete_unmatched or p.is_area():
                        count_retagged += 1
                    else:
                        count_deleted += 1
                    self.register_match(None, k, keep=not delete_unmatched, retag=retag)
            logging.info('Deleted %s and retagged %s unmatched objects from OSM', count_deleted, count_retagged)

    def backup_osm(self):
        """Writes OSM data as-is."""
        osm = etree.Element('osm', version='0.6', generator=TITLE)
        for osmel in self.osmdata.values():
            el = osmel.to_xml()
            if osmel.osm_type != 'node':
                etree.SubElement(el, 'center', lat=str(osmel.lat), lon=str(osmel.lon))
            osm.append(el)
        return "<?xml version='1.0' encoding='utf-8'?>\n" + etree.tostring(osm, encoding='utf-8').decode('utf-8')

    def to_osc(self, josm=False):
        """Returns a string with osmChange or JOSM XML."""
        osc = etree.Element('osm' if josm else 'osmChange', version='0.6', generator=TITLE)
        if josm:
            neg_id = -1
            changeset = etree.SubElement(osc, 'changeset')
            ch_tags = {
                'source': self.source,
                'created_by': TITLE,
                'type': 'import'
            }
            for k, v in ch_tags.items():
                etree.SubElement(changeset, 'tag', k=k, v=v)
        for osmel in self.matched:
            if osmel.action is not None:
                el = osmel.to_xml()
                if josm:
                    if osmel.action == 'create':
                        el.set('id', str(neg_id))
                        neg_id -= 1
                    else:
                        el.set('action', osmel.action)
                    osc.append(el)
                else:
                    etree.SubElement(osc, osmel.action).append(el)
        return "<?xml version='1.0' encoding='utf-8'?>\n" + etree.tostring(osc, encoding='utf-8').decode('utf-8')


def read_dataset(profile, fileobj):
    """A helper function to call a "dataset" function in the profile.
    If the fileobj is not specified, tries to download a dataset from
    an URL specified in "download_url" profile variable."""
    if not fileobj:
        url = profile.get('download_url')
        if url is None:
            logging.error('No download_url specified in the profile, please provide a dataset file with --source')
            return None
        r = requests.get(url)
        if r.status_code != 200:
            logging.error('Could not download source data: %s %s', r.status_code, r.text)
            return None
        if len(r.content) == 0:
            logging.error('Empty response from %s', url)
            return None
        fileobj = BytesIO(r.content)
    if not profile.has('dataset'):
        # The default option is to parse the source as a JSON
        try:
            data = []
            reader = codecs.getreader('utf-8')
            for item in json.load(reader(fileobj)):
                data.append(SourcePoint(item['id'], item['lat'], item['lon'], item['tags']))
            return data
        except Exception:
            logging.error('Failed to parse the source as a JSON')
    return profile.get('dataset', args=(fileobj,), required='returns a list of SourcePoints with the dataset')


def transform_dataset(profile, dataset):
    """Transforms tags in the dataset using the "transform" method in the profile
    or the instructions in that field in string or dict form."""
    transform = profile.get_raw('transform')
    if not transform:
        return
    if callable(transform):
        for d in dataset:
            transform(d.tags)
        return
    if isinstance(transform, str):
        # Convert string of "key=value|rule1|rule2" lines to a dict
        lines = [line.split('=', 1) for line in transform.splitlines()]
        transform = {l[0].strip(): l[1].strip() for l in lines}
    if not transform or not isinstance(transform, dict):
        return
    for key in transform:
        if isinstance(transform[key], str):
            transform[key] = [x.strip() for x in transform[key].split('|')]

    for d in dataset:
        for key, rules in transform.items():
            if not rules:
                continue
            value = None
            if callable(rules):
                # The value can be generated
                value = rules(None if key not in d.tags else d.tags[key])
                if value is None and key in d.tags:
                    del d.tags[key]
            elif not rules[0]:
                # Use the value of the tag
                if key in d.tags:
                    value = d.tags[key]
            elif not isinstance(rules[0], str):
                # If the value is not a string, use it
                value = str(rules[0])
            elif rules[0][0] == '.':
                # Use the value from another tag
                alt_key = rules[0][1:]
                if alt_key in d.tags:
                    value = d.tags[alt_key]
            elif rules[0][0] == '>':
                # Replace the key
                if key in d.tags:
                    d.tags[rules[0][1:]] = d.tags[key]
                    del d.tags[key]
            elif rules[0][0] == '<':
                # Replace the key, the same but backwards
                alt_key = rules[0][1:]
                if alt_key in d.tags:
                    d.tags[key] = d.tags[alt_key]
                    del d.tags[alt_key]
            elif rules[0] == '-':
                # Delete the tag
                if key in d.tags:
                    del d.tags[key]
            else:
                # Take the value as written
                value = rules[0]
            if value is None:
                continue
            if isinstance(rules, list):
                for rule in rules[1:]:
                    if rule == 'lower':
                        value = value.lower()
            d.tags[key] = value


def run(profile=None):
    parser = argparse.ArgumentParser(description='''
                                     {}.
                                     Reads a profile with source data and conflates it with OpenStreetMap data.
                                     Produces an JOSM XML file ready to be uploaded.'''.format(TITLE))
    if not profile:
        parser.add_argument('profile', type=argparse.FileType('r'), help='Name of a profile (python or json) to use')
    parser.add_argument('-i', '--source', type=argparse.FileType('rb'), help='Source file to pass to the profile dataset() function')
    parser.add_argument('-o', '--output', type=argparse.FileType('w'), default=sys.stdout, help='Output OSM XML file name')
    parser.add_argument('--osc', action='store_true', help='Produce an osmChange file instead of JOSM XML')
    parser.add_argument('--osm', help='Instead of querying Overpass API, use this unpacked osm file. Create one from Overpass data if not found')
    parser.add_argument('-c', '--changes', type=argparse.FileType('w'), help='Write changes as GeoJSON for visualization')
    parser.add_argument('--verbose', '-v', action='count', help='Display info messages, use -vv for debugging')
    options = parser.parse_args()

    if options.verbose == 2:
        log_level = logging.DEBUG
    elif options.verbose == 1:
        log_level = logging.INFO
    else:
        log_level = logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if not profile:
        logging.debug('Loading profile %s', options.profile)
    profile = Profile(profile or options.profile)

    dataset = read_dataset(profile, options.source)
    if not dataset:
        logging.error('Empty source dataset')
        sys.exit(2)
    transform_dataset(profile, dataset)
    logging.info('Read %s items from the dataset', len(dataset))

    conflator = OsmConflator(profile, dataset)
    if options.osm and os.path.exists(options.osm):
        with open(options.osm, 'r') as f:
            conflator.parse_osm(f)
    else:
        conflator.download_osm()
        if len(conflator.osmdata) > 0 and options.osm:
            with open(options.osm, 'w') as f:
                f.write(conflator.backup_osm())
    logging.info('Downloaded %s objects from OSM', len(conflator.osmdata))

    conflator.match()

    diff = conflator.to_osc(not options.osc)
    options.output.write(diff)
    if options.changes:
        fc = {'type': 'FeatureCollection', 'features': conflator.changes}
        json.dump(fc, options.changes, ensure_ascii=False, sort_keys=True, indent=1)


if __name__ == '__main__':
    run()
