import struct
import logging
import os
import kdtree


class Geocoder:
    def __init__(self, profile_regions='all'):
        self.filter = None
        self.enabled = bool(profile_regions)
        if self.enabled:
            logging.info('Initializing geocoder (this will take a minute)')
            self.regions = self.parse_regions(profile_regions)
            self.tree = self.load_places_tree()
            if not self.tree:
                if callable(profile_regions):
                    logging.warn('Could not read the geocoding file')
                else:
                    logging.error('Could not read the geocoding file, no regions will be added')
                    self.enabled = False

    def set_filter(self, opt_regions):
        if isinstance(opt_regions, str):
            self.f_negate = opt_regions[0] in ('-', '^')
            if self.f_negate:
                opt_regions = opt_regions[1:]
            self.filter = set([r.strip() for r in opt_regions.split(',')])
        elif isinstance(opt_regions, list):
            self.f_negate = False
            self.filter = set(opt_regions)

    def load_places_tree(self):
        class PlacePoint:
            def __init__(self, lon, lat, country, region):
                self.coord = (lon, lat)
                self.country = country
                self.region = region

            def __len__(self):
                return len(self.coord)

            def __getitem__(self, i):
                return self.coord[i]

        def unpack_coord(data):
            if data[-1] > 0x7f:
                data += b'\xFF'
            else:
                data += b'\0'
            return struct.unpack('<l', data)[0] / 10000

        filename = os.path.join(os.getcwd(), os.path.dirname(__file__), 'places.bin')
        if not os.path.exists(filename):
            return None
        places = []
        with open(filename, 'rb') as f:
            countries = []
            cnt = struct.unpack('B', f.read(1))[0]
            for i in range(cnt):
                countries.append(struct.unpack('2s', f.read(2))[0].decode('ascii'))
            regions = []
            cnt = struct.unpack('<h', f.read(2))[0]
            for i in range(cnt):
                l = struct.unpack('B', f.read(1))[0]
                regions.append(f.read(l).decode('ascii'))
            dlon = f.read(3)
            while len(dlon) == 3:
                dlat = f.read(3)
                country = struct.unpack('B', f.read(1))[0]
                region = struct.unpack('<h', f.read(2))[0]
                places.append(PlacePoint(unpack_coord(dlon), unpack_coord(dlat),
                                         countries[country], regions[region]))
                dlon = f.read(3)
        if not places:
            return None
        return kdtree.create(places)

    def parse_regions(self, profile_regions):
        if not profile_regions or callable(profile_regions):
            return profile_regions
        regions = profile_regions
        if regions is True or regions == 4:
            regions = 'all'
        elif regions is False or regions == 2:
            regions = []
        if isinstance(regions, str):
            regions = regions.lower()
            if regions[:3] == 'reg' or '4' in regions:
                regions = 'all'
            elif regions[:3] == 'cou' or '2' in regions:
                regions = []
            elif regions == 'some':
                regions = ['US', 'RU']
        if isinstance(regions, set):
            regions = list(regions)
        if isinstance(regions, dict):
            regions = list(regions.keys())
        if isinstance(regions, list):
            for i in regions:
                regions[i] = regions[i].upper()
            regions = set(regions)
        return regions

    def find(self, pt):
        """Returns a tuple of (region, present). A point should be skipped if not present."""
        region = pt.region
        if self.enabled:
            if not self.tree:
                if callable(self.regions):
                    region = self.regions(pt, region)
            elif region is None:
                reg, _ = self.tree.search_nn(pt)
                if callable(self.regions):
                    region = self.regions(pt, reg.data.region)
                elif self.regions == 'all' or reg.data.country in self.regions:
                    region = reg.data.region
                else:
                    region = reg.data.country

        return region, not self.filter or (self.negate != (region not in self.filter))
