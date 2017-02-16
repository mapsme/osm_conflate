# Available modules: logging, requests, json, re, etree. But importing these helps catch other errors
import json
import re
import logging

# Verify this at http://data.mos.ru/opendata/1421/passport ("Download .json")
# Disabled since the link returns a zip file and not a plain json
# download_url = 'http://op.mos.ru/EHDWSREST/catalog/export/get?id=89786'

# What will be put into "source" tags. Lower case please
source = 'dit.mos.ru'
# A fairly unique id of the dataset to query OSM, used for "ref:mos_parking" tags
# If you omit it, set explicitly "no_dataset_id = True"
dataset_id = 'mos_parking'
# Tags for querying with overpass api
query = [('amenity', 'vending_machine'), ('vending', 'parking_tickets')]
# Use bbox from dataset points (default). False = query whole world, [minlat, minlon, maxlat, maxlon] to override
bbox = True
# How close OSM point should be to register a match. Default is 0.001 (~110 m)
max_distance = 0.0003  # ~30 m
# Delete objects that match query tags but not dataset? False is the default
delete_unmatched = False
# If set, and delete_unmatched is False, modify tags on unmatched objects instead
# Always used for area features, since these are not deleted
tag_unmatched = {
    'fixme': 'Проверить на местности: в данных ДИТ отсутствует. Вероятно, демонтирован',
    'amenity': None,
    'was:amenity': 'vending_machine'
}
# A set of authoritative tags to replace on matched objects
master_tags = ('zone:parking', 'ref', 'contact:phone', 'contact:website', 'operator')


# A list of SourcePoint objects. Initialize with (id, lat, lon, {tags}).
def dataset(fileobj):
    source = json.loads(fileobj.read().decode('cp1251'))
    RE_NUM4 = re.compile(r'\d{4,6}')
    data = []
    for el in source:
        try:
            gid = el['global_id']
            zone = el['ParkingZoneNumber']
            lon = el['Longitude_WGS84']
            lat = el['Latitude_WGS84']
            pnum = el['NumberOfParkingMeter']
            tags = {
                'amenity': 'vending_machine',
                'vending': 'parking_tickets',
                'zone:parking': zone,
                'contact:phone': '+7 495 539-54-54',
                'contact:website': 'http://parking.mos.ru/',
                'opening_hours': '24/7',
                'operator': 'ГКУ «Администратор Московского парковочного пространства»',
                'payment:cash': 'no',
                'payment:credit_cards': 'yes',
                'payment:debit_cards': 'yes'
            }
            try:
                lat = float(lat)
                lon = float(lon)
                tags['ref'] = RE_NUM4.search(pnum).group(0)
                data.append(SourcePoint(gid, lat, lon, tags))
            except Exception as e:
                logging.warning('PROFILE: Failed to parse lat/lon/ref for parking meter %s: %s', gid, str(e))
        except Exception as e:
            logging.warning('PROFILE: Failed to get attributes for parking meter: %s', str(e))
    return data
