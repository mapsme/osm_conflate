# Where to get the latest feed
download_url = 'http://www.velobike.ru/proxy/parkings/'
# What to write for the changeset's source tag
source = 'velobike.ru'
# These two lines negate each other:
dataset_id = 'velobike'
# We actually do not use ref:velobike tag
no_dataset_id = True
# Overpass API query: [amenity="bicycle_rental"][network="Велобайк"]
query = [('amenity', 'bicycle_rental'), ('network', 'Велобайк')]
# Maximum lookup radius is 100 meters
max_distance = 100
# The overpass query chooses all relevant points,
# so points that are not in the dataset should be deleted
delete_unmatched = True
# If delete_unmatched were False, we'd be retagging these parkings:
tag_unmatched = {
    'fixme': 'Проверить на местности: в данных велобайка отсутствует. Вероятно, демонтирована',
    'amenity': None,
    'was:amenity': 'bicycle_rental'
}
# Overwriting these tags
master_tags = ('ref', 'capacity', 'capacity:electric', 'contact:email',
               'contact:phone', 'contact:website', 'operator')


def dataset(fileobj):
    import codecs
    import json
    import logging

    # Specifying utf-8 is important, otherwise you'd get "bytes" instead of "str"
    source = json.load(codecs.getreader('utf-8')(fileobj))
    data = []
    for el in source['Items']:
        try:
            gid = int(el['Id'])
            lon = el['Position']['Lon']
            lat = el['Position']['Lat']
            terminal = 'yes' if el['HasTerminal'] else 'no'
            tags = {
                'amenity': 'bicycle_rental',
                'network': 'Велобайк',
                'ref': gid,
                'capacity': el['TotalOrdinaryPlaces'],
                'capacity:electric': el['TotalElectricPlaces'],
                'contact:email': 'info@velobike.ru',
                'contact:phone': '+7 495 966-46-69',
                'contact:website': 'https://velobike.ru/',
                'opening_hours': '24/7',
                'operator': 'ЗАО «СитиБайк»',
                'payment:cash': 'no',
                'payment:troika': 'no',
                'payment:mastercard': terminal,
                'payment:visa': terminal,
            }
            try:
                lat = float(lat)
                lon = float(lon)
                data.append(SourcePoint(gid, lat, lon, tags))
            except Exception as e:
                logging.warning('PROFILE: Failed to parse lat/lon for rental stand %s: %s', gid, str(e))
        except Exception as e:
            logging.warning('PROFILE: Failed to get attributes for rental stand: %s', str(e))
    return data
