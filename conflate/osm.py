import logging
import requests
import re
from .data import OSMPoint
from . import etree


OVERPASS_SERVER = 'https://overpass-api.de/api/'
ALT_OVERPASS_SERVER = 'https://overpass.kumi.systems/api/'
OSM_API_SERVER = 'https://api.openstreetmap.org/api/0.6/'
BBOX_PADDING = 0.003  # in degrees, ~330 m default


class OsmDownloader:
    def __init__(self, profile):
        self.profile = profile

    def set_overpass(self, server='alt'):
        global OVERPASS_SERVER
        if server == 'alt':
            OVERPASS_SERVER = ALT_OVERPASS_SERVER
        else:
            OVERPASS_SERVER = server

    def construct_overpass_query(self, bboxes):
        """Constructs an Overpass API query from the "query" list in the profile.
        (k, v) turns into [k=v], (k,) into [k], (k, None) into [!k], (k, "~v") into [k~v]."""
        tags = self.profile.get(
            'query', required="a list of tuples. E.g. [('amenity', 'cafe'), ('name', '~Mc.*lds')]")
        tag_strs = []
        if isinstance(tags, str):
            tag_strs = [tags]
        else:
            if not isinstance(tags[0], str) and isinstance(tags[0][0], str):
                tags = [tags]
            for tags_q in tags:
                if isinstance(tags_q, str):
                    tag_strs.append(tags_q)
                    continue
                tag_str = ''
                for t in tags_q:
                    if len(t) == 1:
                        q = '"{}"'.format(t[0])
                    elif t[1] is None or len(t[1]) == 0:
                        q = '"!{}"'.format(t[0])
                    elif t[1][0] == '~':
                        q = '"{}"~"{}",i'.format(t[0], t[1][1:])
                    elif len(t) > 2:
                        q = '"{}"~"^({})$"'.format(t[0], '|'.join(t[1:]))
                    else:
                        q = '"{}"="{}"'.format(t[0], t[1])
                    tag_str += '[' + q + ']'
                tag_strs.append(tag_str)

        if self.profile.get('no_dataset_id', False):
            ref = None
        else:
            ref = 'nwr["ref:' + self.profile.get(
                'dataset_id', required='A fairly unique id of the dataset to query OSM') + '"]'
        timeout = self.profile.get('overpass_timeout', 120)
        query = '[out:xml]{};('.format('' if timeout is None else '[timeout:{}]'.format(timeout))
        for bbox in bboxes:
            bbox_str = '' if bbox is None else '(' + ','.join([str(x) for x in bbox]) + ')'
            for tag_str in tag_strs:
                query += 'nwr' + tag_str + bbox_str + ';'
        if ref is not None:
            if not self.profile.get('bounded_update', False):
                query += ref + ';'
            else:
                for bbox in bboxes:
                    bbox_str = '' if bbox is None else '(' + ','.join(
                        [str(x) for x in bbox]) + ')'
                    query += ref + bbox_str + ';'
        query += '); out meta qt center;'
        return query

    def get_bbox(self, points):
        """Plain iterates over the dataset and returns the bounding box
        that encloses it."""
        padding = self.profile.get('bbox_padding', BBOX_PADDING)
        bbox = [90.0, 180.0, -90.0, -180.0]
        for p in points:
            bbox[0] = min(bbox[0], p.lat - padding)
            bbox[1] = min(bbox[1], p.lon - padding)
            bbox[2] = max(bbox[2], p.lat + padding)
            bbox[3] = max(bbox[3], p.lon + padding)
        return bbox

    def split_into_bboxes(self, points):
        """
        Splits the dataset into multiple bboxes to lower load on the overpass api.

        Returns a list of tuples (minlat, minlon, maxlat, maxlon).
        """
        max_bboxes = self.profile.get('max_request_boxes', 4)
        if max_bboxes <= 1 or len(points) <= 1:
            return [self.get_bbox(points)]

        # coord, alt coord, total w/h to the left/bottom, total w/h to the right/top
        lons = sorted([[d.lon, d.lat, 0, 0] for d in points])
        lats = sorted([[d.lat, d.lon, 0, 0] for d in points])

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
        boxes = [[lats[-1][0]-lats[0][0], lons[-1][0]-lons[0][0], lats, lons]]
        initial_area = boxes[0][0] * boxes[0][1]
        while len(boxes) < max_bboxes and len(boxes) <= len(points):
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
            logging.debug('Splitting bbox %s at %s %s..%s; area decrease %s%%',
                          get_bbox(candidate_box),
                          'longs' if point_array == 3 else 'lats',
                          candidate_box[point_array][point_id][0],
                          candidate_box[point_array][point_id+1][0],
                          round(100*area/initial_area))
            boxes.append(split(candidate_box, point_array, point_id))

        padding = self.profile.get('bbox_padding', BBOX_PADDING)
        return [get_bbox(b, padding) for b in boxes]

    def get_categories(self, tags):
        def match_query(tags, query):
            for tag in query:
                if len(tag) == 1:
                    return tag[0] in tags
                else:
                    value = tags.get(tag[0], None)
                    if tag[1] is None or tag[1] == '':
                        return value is None
                    if value is None:
                        return False
                    found = False
                    for t2 in tag[1:]:
                        if t2[0] == '~':
                            if re.search(t2[1:], value):
                                found = True
                        elif t2[0] == '!':
                            if t2[1:].lower() in value.lower():
                                found = True
                        elif t2 == value:
                            found = True
                        if found:
                            break
                    if not found:
                        return False
            return True

        def tags_to_query(tags):
            return [(k, v) for k, v in tags.items()]

        result = set()
        qualifies = self.profile.get('qualifies', args=tags)
        if qualifies is not None:
            if qualifies:
                result.add(None)
            return result

        # First check default query
        query = self.profile.get('query', None)
        if query is not None:
            if isinstance(query, str):
                result.add(None)
            else:
                if isinstance(query[0][0], str):
                    query = [query]
                for q in query:
                    if match_query(tags, q):
                        result.add(None)
                        break

        # Then check each category if we got these
        categories = self.profile.get('categories', {})
        for name, params in categories.items():
            if 'tags' not in params and 'query' not in params:
                raise ValueError('No tags and query attributes for category "{}"'.format(name))
            if match_query(tags, params.get('query', tags_to_query(params.get('tags')))):
                result.add(name)

        return result

    def calc_boxes(self, dataset_points):
        profile_bbox = self.profile.get('bbox', True)
        if not profile_bbox:
            bboxes = [None]
        elif hasattr(profile_bbox, '__len__') and len(profile_bbox) == 4:
            bboxes = [profile_bbox]
        else:
            bboxes = self.split_into_bboxes(dataset_points)
        return bboxes

    def download(self, bboxes=None):
        """Constructs an Overpass API query and requests objects
        to match from a server."""
        if not bboxes:
            pbbox = self.profile.get('bbox', True)
            if pbbox and hasattr(pbbox, '__len__') and len(pbbox) == 4:
                bboxes = [pbbox]
            else:
                bboxes = [None]

        query = self.construct_overpass_query(bboxes)
        logging.debug('Overpass query: %s', query)
        r = requests.get(OVERPASS_SERVER + 'interpreter', {'data': query})
        if r.encoding is None:
            r.encoding = 'utf-8'
        if r.status_code != 200:
            logging.error('Failed to download data from Overpass API: %s', r.status_code)
            if 'rate_limited' in r.text:
                r = requests.get(OVERPASS_SERVER + 'status')
                logging.warning('Seems like you are rate limited. API status:\n%s', r.text)
            else:
                logging.error('Error message: %s', r.text)
            raise IOError()
        if 'runtime error: ' in r.text:
            m = re.search(r'runtime error: ([^<]+)', r.text)
            error = 'unknown' if not m else m.group(1)
            if 'Query timed out' in error:
                logging.error(
                    'Query timed out, try increasing the "overpass_timeout" profile variable')
            else:
                logging.error('Runtime error: %s', error)
            raise IOError()
        return self.parse_xml(r.content)

    def parse_xml(self, fileobj):
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
                logging.debug('Way %s does not have a center', way.get('id'))
                coord = [0, 0]
                count = 0
                for nd in way.findall('nd'):
                    if nd.get('ref') in nodes:
                        count += 1
                        for i in range(len(coord)):
                            coord[i] += nodes[nd.get('ref')][i]
                ways[way.get('id')] = [coord[0] / count, coord[1] / count]

        # For calculating weight of OSM objects
        weight_fn = self.profile.get_raw('weight')
        osmdata = {}

        for el in xml:
            tags = {}
            for tag in el.findall('tag'):
                tags[tag.get('k')] = tag.get('v')
            categories = self.get_categories(tags)
            if categories is False or categories is None or len(categories) == 0:
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
                    logging.debug('Relation %s does not have a center', el.get('id'))
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
                    if count > 0:
                        coord = [coord[0] / count, coord[1] / count]
                members = [
                    (m.get('type'), m.get('ref'), m.get('role'))
                    for m in el.findall('member')
                ]
            else:
                continue
            if not coord or coord == [0, 0]:
                continue
            pt = OSMPoint(
                el.tag, int(el.get('id')), int(el.get('version')),
                coord[0], coord[1], tags, categories)
            pt.members = members
            if pt.is_poi():
                if callable(weight_fn):
                    weight = weight_fn(pt)
                    if weight:
                        if abs(weight) > 3:
                            pt.dist_offset = weight
                        else:
                            pt.dist_offset = weight * self.profile.max_distance
                osmdata[pt.id] = pt
        return osmdata


def check_moveability(changes):
    to_check = [x for x in changes if x['properties']['osm_type'] == 'node' and
                x['properties']['action'] == 'modify']
    logging.info('Checking moveability of %s modified nodes', len(to_check))
    for c in to_check:
        p = c['properties']
        p['can_move'] = False
        r = requests.get('{}node/{}/ways'.format(OSM_API_SERVER, p['osm_id']))
        if r.status_code == 200:
            xml = etree.fromstring(r.content)
            p['can_move'] = xml.find('way') is None
