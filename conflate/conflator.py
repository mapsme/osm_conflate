import logging
import kdtree
from collections import defaultdict
from .data import OSMPoint
from .version import __version__
from .osm import OsmDownloader, check_moveability
from . import etree


TITLE = 'OSM Conflator ' + __version__
CONTACT_KEYS = set(('phone', 'website', 'email', 'fax', 'facebook', 'twitter', 'instagram'))
LIFECYCLE_KEYS = set(('amenity', 'shop', 'tourism', 'craft', 'office'))
LIFECYCLE_PREFIXES = ('proposed', 'construction', 'disused', 'abandoned', 'was', 'removed')


class OsmConflator:
    """The main class for the conflator.

    It receives a dataset, after which one must call either
    "download_osm" or "parse_osm" methods. Then it is ready to match:
    call the "match" method and get results with "to_osc".
    """
    def __init__(self, profile, dataset, audit=None):
        self.dataset = {p.id: p for p in dataset}
        self.audit = audit or {}
        self.osmdata = {}
        self.matched = []
        self.changes = []
        self.matches = []
        self.profile = profile
        self.geocoder = None
        self.downloader = OsmDownloader(profile)
        self.source = self.profile.get(
            'source', required='value of "source" tag for uploaded OSM objects')
        self.add_source_tag = self.profile.get('add_source', False)
        if self.profile.get('no_dataset_id', False):
            self.ref = None
        else:
            self.ref = 'ref:' + self.profile.get(
                'dataset_id', required='A fairly unique id of the dataset to query OSM')

    def set_overpass(self, server='alt'):
        self.downloader.set_overpass(server)

    def download_osm(self):
        bboxes = self.downloader.calc_boxes(self.dataset.values())
        self.osmdata = self.downloader.download(bboxes)

    def parse_osm(self, fileobj):
        self.osmdata = self.downloader.parse_xml(fileobj)

    def register_match(self, dataset_key, osmdata_key, keep=False, retag=None):
        """Registers a match between an OSM point and a dataset point.

        Merges tags from an OSM Point and a dataset point, and add the result to the
        self.matched list.
        If dataset_key is None, deletes or retags the OSM point.
        If osmdata_key is None, adds a new OSM point for the dataset point.
        """
        def get_osm_key(k, osm_tags):
            """Conflating contact: namespace."""
            if k in CONTACT_KEYS and k not in osm_tags and 'contact:'+k in osm_tags:
                return 'contact:'+k
            elif k.startswith('contact:') and k not in osm_tags and k[8:] in osm_tags:
                return k[8:]

            # Now conflating lifecycle prefixes, only forward
            if k in LIFECYCLE_KEYS and k not in osm_tags:
                for prefix in LIFECYCLE_PREFIXES:
                    if prefix+':'+k in osm_tags:
                        return prefix+':'+k
            return k

        def update_tags(tags, source, master_tags=None, retagging=False, audit=None):
            """Updates tags dictionary with tags from source,
            returns True is something was changed."""
            keep = set()
            override = set()
            changed = False
            if source:
                if audit:
                    keep = set(audit.get('keep', []))
                    override = set(audit.get('override', []))
                for k, v in source.items():
                    osm_key = get_osm_key(k, tags)

                    if k in keep or osm_key in keep:
                        continue
                    if k in override or osm_key in override:
                        if not v and osm_key in tags:
                            del tags[osm_key]
                            changed = True
                        elif v and tags.get(osm_key, None) != v:
                            tags[osm_key] = v
                            changed = True
                        continue

                    if osm_key not in tags or retagging or (
                            tags[osm_key] != v and (master_tags and k in master_tags)):
                        if v is not None and len(v) > 0:
                            # Not setting addr:full when the object has addr:housenumber
                            if k == 'addr:full' and 'addr:housenumber' in tags:
                                continue
                            tags[osm_key] = v
                            changed = True
                        elif osm_key in tags and (v == '' or retagging):
                            del tags[osm_key]
                            changed = True
            return changed

        def format_change(before, after, ref):
            MARKER_COLORS = {
                'delete': '#ee2211',  # deleting feature from OSM
                'create': '#11dd11',  # creating a new node
                'update': '#0000ee',  # changing tags on an existing feature
                'retag':  '#660000',  # cannot delete unmatched feature, changing tags
                'move':   '#110055',  # moving an existing node
            }
            marker_action = None
            geometry = {'type': 'Point', 'coordinates': [after.lon, after.lat]}
            props = {
                'osm_type': after.osm_type,
                'osm_id': after.osm_id,
                'action': after.action
            }
            if after.action in ('create', 'delete'):
                # Red if deleted, green if added
                marker_action = after.action
                for k, v in after.tags.items():
                    props['tags.{}'.format(k)] = v
                if ref:
                    props['ref_id'] = ref.id
            else:  # modified
                # Blue if updated from dataset, dark red if retagged, dark blue if moved
                marker_action = 'update' if ref else 'retag'
                if ref:
                    props['ref_id'] = ref.id
                    props['ref_distance'] = round(10 * ref.distance(before)) / 10.0
                    props['ref_coords'] = [ref.lon, ref.lat]
                    if before.lon != after.lon or before.lat != after.lat:
                        # The object was moved
                        props['were_coords'] = [before.lon, before.lat]
                        marker_action = 'move'
                    # Find tags that were superseeded by OSM tags
                    for k, v in ref.tags.items():
                        osm_key = get_osm_key(k, after.tags)
                        if osm_key not in after.tags or after.tags[osm_key] != v:
                            props['ref_unused_tags.{}'.format(osm_key)] = v
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
            props['marker-color'] = MARKER_COLORS[marker_action]
            if ref and ref.remarks:
                props['remarks'] = ref.remarks
            if ref and ref.region:
                props['region'] = ref.region
            elif self.geocoder:
                region, present = self.geocoder.find(after)
                if not present:
                    return None
                if region is not None:
                    props['region'] = region
            return {'type': 'Feature', 'geometry': geometry, 'properties': props}

        p = self.osmdata.pop(osmdata_key, None)
        p0 = None if p is None else p.copy()
        sp = self.dataset.pop(dataset_key, None)
        audit = self.audit.get(sp.id if sp else '{}{}'.format(p.osm_type, p.osm_id), {})
        if audit.get('skip', False):
            return

        if sp is not None:
            if p is None:
                p = OSMPoint('node', -1-len(self.matched), 1, sp.lat, sp.lon, sp.tags)
                p.action = 'create'
            else:
                master_tags = set(self.profile.get('master_tags', []))
                if update_tags(p.tags, sp.tags, master_tags, audit=audit):
                    p.action = 'modify'
                # Move a node if it is too far from the dataset point
                if not p.is_area() and sp.distance(p) > self.profile.max_distance:
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
            if 'fixme' in audit and audit['fixme'] != p.tags.get('fixme'):
                p.tags['fixme'] = audit['fixme']
                if p.action is None:
                    p.action = 'modify'
            if 'move' in audit and not p.is_area():
                if p0 and audit['move'] == 'osm':
                    p.lat = p0.lat
                    p.lon = p0.lon
                elif audit['move'] == 'dataset':
                    p.lat = sp.lat
                    p.lon = sp.lon
                elif len(audit['move']) == 2:
                    p.lat = audit['move'][1]
                    p.lon = audit['move'][0]
                if p.action is None and p0.distance(p) > 0.1:
                    p.action = 'modify'
            if p.action != 'create':
                self.matches.append([sp.id, p.osm_type, p.osm_id, p.lat, p.lon, p.action])
            else:
                self.matches.append([sp.id, '', '', p.lat, p.lon, p.action])
        elif keep or p.is_area():
            if update_tags(p.tags, retag, retagging=True, audit=audit):
                p.action = 'modify'
        else:
            p.action = 'delete'

        if p.action is not None:
            change = format_change(p0, p, sp)
            if change is not None:
                self.matched.append(p)
                self.changes.append(change)

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
            nearest = kd.search_knn(point, self.profile.get('nearest_points', 10))
            if not nearest:
                return None, None
            match_func = self.profile.get_raw('matches')
            if match_func:
                nearest = [p for p in nearest if match_func(p[0].data.tags, point.tags)]
                if not nearest:
                    return None, None
            nearest = [(n[0], n[0].data.distance(point))
                       for n in nearest if point.category in n[0].data.categories]
            return sorted(nearest, key=lambda kv: kv[1])[0]

        if not self.osmdata:
            return
        osm_kd = kdtree.create(list(self.osmdata.values()))
        count_matched = 0

        # Process overridden features first
        for override, osm_find in self.profile.get('override', {}).items():
            override = str(override)
            if override not in self.dataset:
                continue
            found = None
            if len(osm_find) > 2 and osm_find[0] in 'nwr' and osm_find[1].isdigit():
                if osm_find in self.osmdata:
                    found = self.osmdata[osm_find]
            # Search nearest 100 points
            nearest = osm_kd.search_knn(self.dataset[override], 100)
            if nearest:
                for p in nearest:
                    if 'name' in p[0].data.tags and p[0].data.tags['name'] == osm_find:
                        found = p[0].data
            if found:
                count_matched += 1
                self.register_match(override, found.id)
                osm_kd = osm_kd.remove(found)

        # Prepare distance list: match OSM points to each of the dataset points
        dist = []
        for sp, v in self.dataset.items():
            osm_point, distance = search_nn_fix(osm_kd, v)
            if osm_point is not None and distance <= self.profile.max_distance:
                dist.append((distance, sp, osm_point.data))

        # The main matching loop: sort dist list if needed,
        # register the closes match, update the list
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
            for i in reversed(range(len(dist))):
                if dist[i][2] == osm_point:
                    nearest, distance = search_nn_fix(osm_kd, self.dataset[dist[i][1]])
                    if nearest and distance <= self.profile.max_distance:
                        dist[i] = (distance, dist[i][1], nearest.data)
                        needs_sorting = i == 0 or distance < dist[0][0]
                    else:
                        del dist[i]
                        needs_sorting = i == 0
        logging.info('Matched %s points', count_matched)

    def match(self):
        """Matches each osm object with a SourcePoint, or marks it as obsolete.
        The resulting list of OSM Points are written to the "matched" field."""
        find_ref = self.profile.get_raw('find_ref')
        if self.ref is not None or callable(find_ref):
            # First match all objects with ref:whatever tag set
            count_ref = 0
            for k, p in list(self.osmdata.items()):
                ref = None
                if self.ref and self.ref in p.tags:
                    ref = p.tags[self.ref]
                elif find_ref:
                    ref = find_ref(p.tags)
                if ref is not None:
                    if ref in self.dataset:
                        count_ref += 1
                        self.register_match(ref, k)
            logging.info('Updated %s OSM objects with %s tag', count_ref, self.ref)

        # Add points for which audit specifically mentioned creating
        count_created = 0
        for ref, a in self.audit.items():
            if ref in self.dataset:
                if a.get('create', None):
                    count_created += 1
                    self.register_match(ref, None)
                elif a.get('skip', None):
                    # If we skip an object here, it would affect the conflation order
                    pass
        if count_created > 0:
            logging.info('Created %s audit-overridden dataset points', count_created)

        # Prepare exclusive groups dict
        exclusive_groups = defaultdict(set)
        for p, v in self.dataset.items():
            if v.exclusive_group is not None:
                exclusive_groups[v.exclusive_group].add(p)

        # Then find matches for unmatched dataset points
        self.match_dataset_points_smart()

        # Remove unmatched duplicates
        count_duplicates = 0
        for ids in exclusive_groups.values():
            found = False
            for p in ids:
                if p not in self.dataset:
                    found = True
                    break
            for p in ids:
                if p in self.dataset:
                    if found:
                        count_duplicates += 1
                        del self.dataset[p]
                    else:
                        # Leave one element when not matched any
                        found = True
        if count_duplicates > 0:
            logging.info('Removed %s unmatched duplicates', count_duplicates)

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
                ref = None
                if self.ref and self.ref in p.tags:
                    ref = p.tags[self.ref]
                elif find_ref:
                    ref = find_ref(p.tags)
                if ref is not None:
                    # When ref:whatever is present, we can delete that object safely
                    count_deleted += 1
                    self.register_match(None, k, retag=retag)
                elif delete_unmatched or retag:
                    if not delete_unmatched or p.is_area():
                        count_retagged += 1
                    else:
                        count_deleted += 1
                    self.register_match(None, k, keep=not delete_unmatched, retag=retag)
            logging.info(
                'Deleted %s and retagged %s unmatched objects from OSM',
                count_deleted, count_retagged)

    def backup_osm(self):
        """Writes OSM data as-is."""
        osm = etree.Element('osm', version='0.6', generator=TITLE)
        for osmel in self.osmdata.values():
            el = osmel.to_xml()
            if osmel.osm_type != 'node':
                etree.SubElement(el, 'center', lat=str(osmel.lat), lon=str(osmel.lon))
            osm.append(el)
        return ("<?xml version='1.0' encoding='utf-8'?>\n" +
                etree.tostring(osm, encoding='utf-8').decode('utf-8'))

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
        return ("<?xml version='1.0' encoding='utf-8'?>\n" +
                etree.tostring(osc, encoding='utf-8').decode('utf-8'))

    def check_moveability(self):
        check_moveability(self.changes)
