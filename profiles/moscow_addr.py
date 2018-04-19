import json
import logging

source = 'dit.mos.ru'
no_dataset_id = True
query = [[('addr:housenumber',)], [('building',)]]
max_distance = 50
max_request_boxes = 2
master_tags = ('addr:housenumber', 'addr:street')

COMPLEX = False
ADMS = {
    '1': 'Северо-Западный административный округ',
    '2': 'Северный административный округ',
    '3': 'Северо-Восточный административный округ',
    '4': 'Западный административный округ',
    '5': 'Центральный административный округ',
    '6': 'Восточный административный округ',
    '7': 'Юго-Западный административный округ',
    '8': 'Южный административный округ',
    '9': 'Юго-Восточный административный округ',
    '10': 'Зеленоградский административный округ',
    '11': 'Троицкий административный округ',
    '12': 'Новомосковский административный округ',
}
ADM = ADMS['2']
if param:
    if param[0] == 'c':
        COMPLEX = True
        param = param[1:]
    if param in ADMS:
        ADM = ADMS[param]


def dataset(fileobj):
    def find_center(geodata):
        if not geodata:
            return None
        if 'center' in geodata:
            return geodata['center'][0]
        if 'coordinates' in geodata:
            typ = geodata['type']
            lonlat = [0, 0]
            cnt = 0
            if typ == 'Polygon':
                for p in geodata['coordinates'][0]:
                    lonlat[0] += p[0]
                    lonlat[1] += p[1]
                    cnt += 1
            elif typ == 'LineString':
                for p in geodata['coordinates']:
                    lonlat[0] += p[0]
                    lonlat[1] += p[1]
                    cnt += 1
            elif typ == 'Point':
                p = geodata['coordinates']
                lonlat[0] += p[0]
                lonlat[1] += p[1]
                cnt += 1
            if cnt > 0:
                return [lonlat[0]/cnt, lonlat[1]/cnt]
        return None

    global COMPLEX, ADM
    import zipfile
    zf = zipfile.ZipFile(fileobj)
    data = []
    no_geodata = 0
    no_addr = 0
    count = 0
    for zname in zf.namelist():
        source = json.loads(zf.read(zname).decode('cp1251'))
        for el in source:
            gid = el['global_id']
            try:
                adm_area = el['ADM_AREA']
                if adm_area != ADM:
                    continue
                count += 1
                lonlat = find_center(el.get('geoData'))
                if not lonlat:
                    no_geodata += 1
                street = el.get('P7')
                house = el.get('L1_VALUE')
                htype = el.get('L1_TYPE')
                corpus = el.get('L2_VALUE')
                ctype = el.get('L2_TYPE')
                stroenie = el.get('L3_VALUE')
                stype = el.get('L3_TYPE')
                if not street or not house:
                    no_addr += 1
                    continue
                if not lonlat:
                    continue
                is_complex = False
                housenumber = house.replace(' ', '')
                if htype != 'дом':
                    is_complex = True
                    if htype in ('владение', 'домовладение'):
                        housenumber = 'вл' + housenumber
                    else:
                        logging.warn('Unknown house number type: %s', htype)
                        continue
                if corpus:
                    if ctype == 'корпус':
                        housenumber += ' к{}'.format(corpus)
                    else:
                        logging.warn('Unknown corpus type: %s', ctype)
                        continue
                if stroenie:
                    is_complex = True
                    if stype == 'строение' or stype == 'сооружение':
                        housenumber += ' с{}'.format(stroenie)
                    else:
                        logging.warn('Unknown stroenie type: %s', stype)
                        continue
                if is_complex != COMPLEX:
                    continue
                tags = {
                    'addr:street': street,
                    'addr:housenumber': housenumber,
                }
                data.append(SourcePoint(gid, lonlat[1], lonlat[0], tags))
            except Exception as e:
                logging.warning('PROFILE: Failed to get attributes for address %s: %s', gid, str(e))
                logging.warning(json.dumps(el, ensure_ascii=False))

    if no_addr + no_geodata > 0:
        logging.warning('%.2f%% of data have no centers, and %.2f%% have no streets or house numbers',
                        100*no_geodata/count, 100*no_addr/count)
    return data
