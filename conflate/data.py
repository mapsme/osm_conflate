import math
from . import etree


class SourcePoint:
    """A common class for points. Has an id, latitude and longitude,
    and a dict of tags. Remarks are optional for reviewers hints only."""
    def __init__(self, pid, lat, lon, tags=None, category=None, remarks=None, region=None):
        self.id = str(pid)
        self.lat = lat
        self.lon = lon
        self.tags = {} if tags is None else {
            k.lower(): str(v).strip() for k, v in tags.items() if v is not None}
        self.category = category
        self.dist_offset = 0
        self.remarks = remarks
        self.region = region
        self.exclusive_group = None

    def distance(self, other):
        """Calculate distance in meters."""
        dx = math.radians(self.lon - other.lon) * math.cos(0.5 * math.radians(self.lat + other.lat))
        dy = math.radians(self.lat - other.lat)
        return 6378137 * math.sqrt(dx*dx + dy*dy) - self.dist_offset

    def __len__(self):
        return 2

    def __getitem__(self, i):
        if i == 0:
            return self.lon
        elif i == 1:
            return self.lat
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
    def __init__(self, ptype, pid, version, lat, lon, tags=None, categories=None):
        super().__init__('{}{}'.format(ptype[0], pid), lat, lon, tags)
        self.tags = {k: v for k, v in self.tags.items() if v is not None and len(v) > 0}
        self.osm_type = ptype
        self.osm_id = pid
        self.version = version
        self.members = None
        self.action = None
        self.categories = categories or set()
        self.remarks = None

    def copy(self):
        """Returns a copy of this object, except for members field."""
        c = OSMPoint(self.osm_type, self.osm_id, self.version, self.lat, self.lon, self.tags.copy())
        c.action = self.action
        c.remarks = self.remarks
        c.categories = self.categories.copy()
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
