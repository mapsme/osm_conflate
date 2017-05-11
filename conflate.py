#!/usr/bin/env python3
import argparse
import codecs
import kdtree
import logging
import math
import requests
import sys
from io import BytesIO
import json  # for profiles
import re    # for profiles
try:
    from lxml import etree
except ImportError:
    import xml.etree.ElementTree as etree

OVERPASS_SERVER = 'http://overpass-api.de/api/'
BBOX_PADDING = 0.1  # in degrees
MAX_DISTANCE = 100  # how far can object be to be considered a match, in meters


class SourcePoint:
    """A common class for points. Has an id, latitude and longitude,
    and a dict of tags."""
    def __init__(self, pid, lat, lon, tags=None):
        self.id = str(pid)
        self.lat = lat
        self.lon = lon
        self.tags = {} if tags is None else {k: str(v) for k, v in tags.items()}

    def distance(self, other):
        """Calculate distance in meters."""
        dx = math.radians(self.lon - other.lon) * math.cos(0.5 * math.radians(self.lat + other.lat))
        dy = math.radians(self.lat - other.lat)
        return 6378137 * math.sqrt(dx*dx + dy*dy)

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
        s = fileobj.read().replace('\r', '')
        self.profile = {}
        exec(s, globals(), self.profile)

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
        if self.profile.get('no_dataset_id', False):
            self.ref = None
        else:
            self.ref = 'ref:' + self.profile.get('dataset_id', required='A fairly unique id of the dataset to query OSM')

    def construct_overpass_query(self, bbox=None):
        """Constructs an Overpass API query from the "query" list in the profile.
        (k, v) turns into [k=v], (k,) into [k], (k, None) into [!k], (k, "~v") into [k~v]."""
        tags = self.profile.get('query', required="a list of tuples. E.g. [('amenity', 'cafe'), ('name', '~Mc.*lds')]")
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
        query = '[out:json][timeout:120];('
        bbox_str = '' if bbox is None else '(' + ','.join([str(x) for x in bbox]) + ')'
        for t in ('node', 'way', 'relation'):
            query += t + tag_str + bbox_str + ';'
            if self.ref is not None:
                query += t + '["' + self.ref + '"];'
        query += '); out meta center;'
        return query

    def get_dataset_bbox(self):
        """Plain iterates over the dataset and returns the bounding box
        that encloses it."""
        bbox = [90.0, 180.0, -90.0, -180.0]
        for p in self.dataset.values():
            bbox[0] = min(bbox[0], p.lat - BBOX_PADDING)
            bbox[1] = min(bbox[1], p.lon - BBOX_PADDING)
            bbox[2] = max(bbox[2], p.lat + BBOX_PADDING)
            bbox[3] = max(bbox[3], p.lon + BBOX_PADDING)
        return bbox

    def split_into_bboxes(self):
        """
        Splits the dataset into multiple bboxes to lower load on the overpass api.

        Returns a list of tuples (minlat, minlon, maxlat, maxlon).

        Not implemented for now, returns the single big bbox. Not sure if needed.
        """
        # TODO
        return [self.get_dataset_bbox()]

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

        for b in bboxes:
            query = self.construct_overpass_query(b)
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
            for el in r.json()['elements']:
                if 'tags' not in el:
                    continue
                if 'center' in el:
                    for ll in ('lat', 'lon'):
                        el[ll] = el['center'][ll]
                if self.check_against_profile_tags(el['tags']):
                    pt = OSMPoint(el['type'], el['id'], el['version'], el['lat'], el['lon'], el['tags'])
                    if 'nodes' in el:
                        pt.members = el['nodes']
                    elif 'members' in el:
                        pt.members = [(x['type'], x['ref'], x['role']) for x in el['members']]
                    if pt.is_poi():
                        self.osmdata[pt.id] = pt

    def parse_osm(self, fileobj):
        """Parses an OSM XML file into the "osmdata" field. For ways and relations,
        finds the center. Drops objects that do not match the overpass query tags
        (see "check_against_profile_tags" method)."""
        xml = etree.parse(fileobj).getroot()
        nodes = {}
        for nd in xml.findall('node'):
            nodes[nd.get('id')] = (float(nd.get('lat')), float(nd.get('lon')))
        ways = {}
        for way in xml.findall('way'):
            coord = [0, 0]
            count = 0
            for nd in way.findall('nd'):
                if nd.get('id') in nodes:
                    count += 1
                    for i in range(len(coord)):
                        coord[i] += nodes[nd.get('ref')][i]
            ways[way.get('id')] = [coord[0] / count, coord[1] / count]

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
            pt = OSMPoint(el.tag, el.get('id'), el.get('version'), coord[0], coord[1], tags)
            pt.members = members
            if pt.is_poi():
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
            source = self.profile.get('source', required='value of "source" tag for uploaded OSM objects')
            p.tags['source'] = source
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
        if not self.osmdata:
            return
        max_distance = self.profile.get('max_distance', MAX_DISTANCE)
        osm_kd = kdtree.create(list(self.osmdata.values()))
        count_matched = 0
        dist = []
        for sp, v in self.dataset.items():
            osm_point, _ = osm_kd.search_nn(v)
            distance = None if osm_point is None else v.distance(osm_point.data)
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
                    nearest = osm_kd.search_nn(self.dataset[dist[i][1]])
                    distance = None if nearest is None else self.dataset[dist[i][1]].distance(nearest[0].data)
                    if nearest and distance <= max_distance:
                        new_point = nearest[0]
                        dist[i] = (distance, dist[i][1], new_point.data)
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
        for k in list(self.dataset.keys()):
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

    def to_osc(self):
        """Returns a string with osmChange."""
        osc = etree.Element('osmChange', version='0.6', generator='OSM Conflator')
        for osmel in self.matched:
            if osmel.action is not None:
                el = osmel.to_xml()
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='''
                                     OSM Conflator.
                                     Reads a profile with source data and conflates it with OpenStreetMap data.
                                     Produces an osmChange file ready to be uploaded.''')
    parser.add_argument('profile', type=argparse.FileType('r'), help='Name of a profile to use')
    parser.add_argument('-o', '--osc', type=argparse.FileType('w'), default=sys.stdout, help='Output osmChange file name')
    parser.add_argument('-i', '--source', type=argparse.FileType('rb'), help='Source file to pass to the profile dataset() function')
    parser.add_argument('--osm', type=argparse.FileType('r'), help='Instead of querying Overpass API, use this unpacked osm file')
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

    logging.debug('Loading profile %s', options.profile)
    profile = Profile(options.profile)

    dataset = read_dataset(profile, options.source)
    if not dataset:
        logging.error('Empty source dataset')
        sys.exit(2)
    logging.info('Read %s items from the dataset', len(dataset))
    conflator = OsmConflator(profile, dataset)
    if options.osm:
        conflator.parse_osm(options.osm)
    else:
        conflator.download_osm()
    logging.info('Downloaded %s objects from OSM', len(conflator.osmdata))
    conflator.match()
    diff = conflator.to_osc()
    options.osc.write(diff)
    if options.changes:
        fc = {'type': 'FeatureCollection', 'features': conflator.changes}
        json.dump(fc, options.changes, ensure_ascii=False, sort_keys=True, indent=1)
