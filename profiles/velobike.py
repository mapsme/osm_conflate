import codecs
import json
import logging

download_url = 'http://www.velobike.ru/proxy/parkings/'
source = 'velobike.ru'
dataset_id = 'velobike'
no_dataset_id = True
query = [('amenity', 'bicycle_rental'), ('network', 'Велобайк')]
max_distance = 100
delete_unmatched = True
tag_unmatched = {
    'fixme': 'Проверить на местности: в данных велобайка отсутствует. Вероятно, демонтирована',
    'amenity': None,
    'was:amenity': 'bicycle_rental'
}
master_tags = ('ref', 'capacity', 'capacity:electric', 'contact:email',
               'contact:phone', 'contact:website', 'operator')


def dataset(fileobj):
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
