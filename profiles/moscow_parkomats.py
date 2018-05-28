# What will be put into "source" tags. Lower case please
source = 'dit.mos.ru'
# A fairly unique id of the dataset to query OSM, used for "ref:mos_parking" tags
# If you omit it, set explicitly "no_dataset_id = True"
dataset_id = 'mos_parking'
# Tags for querying with overpass api
query = [('amenity', 'vending_machine'), ('vending', 'parking_tickets')]
# Use bbox from dataset points (default). False = query whole world, [minlat, minlon, maxlat, maxlon] to override
bbox = True
# How close OSM point should be to register a match, in meters. Default is 100
max_distance = 30
# Delete objects that match query tags but not dataset? False is the default
delete_unmatched = False
# If set, and delete_unmatched is False, modify tags on unmatched objects instead
# Always used for area features, since these are not deleted
tag_unmatched = {
    'fixme': 'Проверить на местности: в данных ДИТ отсутствует. Вероятно, демонтирован',
    'amenity': None,
    'was:amenity': 'vending_machine'
}
# Actually, after the initial upload we should not touch any existing non-matched objects
tag_unmatched = None
# A set of authoritative tags to replace on matched objects
master_tags = ('zone:parking', 'ref', 'contact:phone', 'contact:website', 'operator')


def download_url(mos_dataset_id=1421):
    import requests
    import logging
    r = requests.get('https://data.mos.ru/api/datasets/expformats/?datasetId={}'.format(mos_dataset_id))
    if r.status_code != 200 or len(r.content) == 0:
        logging.error('Could not get URL for dataset: %s %s', r.status_code, r.text)
        logging.error('Please check http://data.mos.ru/opendata/{}/passport'.format(mos_dataset_id))
        return None
    url = [x for x in r.json() if x['Format'] == 'json'][0]
    version = '?'
    title = 'dataset'
    r = requests.get('https://data.mos.ru/apiproxy/opendata/{}/meta.json'.format(mos_dataset_id))
    if r.status_code == 200:
        title = r.json()['Title']
        version = r.json()['VersionNumber']
    logging.info('Downloading %s %s from %s', title, version, url['GenerationStart'])
    return 'https://op.mos.ru/EHDWSREST/catalog/export/get?id=' + url['EhdId']


# A list of SourcePoint objects. Initialize with (id, lat, lon, {tags}).
def dataset(fileobj):
    import json
    import logging
    import zipfile
    import re
    zf = zipfile.ZipFile(fileobj)
    source = json.loads(zf.read(zf.namelist()[0]).decode('cp1251'))
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
