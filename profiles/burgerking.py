import json
import codecs
import re

download_url = 'https://burgerking.ru/restaurant-locations-json-reply-new'
source = 'Burger King'
dataset_id = 'burger_king'
no_dataset_id = True
query = '[amenity~"cafe|restaurant|fast_food"][name~"burger.*king|бургер.*кинг",i]'
max_distance = 1000
overpass_timeout = 1200
max_request_boxes = 4
master_tags = ('name', 'amenity', 'name:ru', 'name:en', 'contact:phone', 'opening_hours')
tag_unmatched = {
    'fixme': 'Проверить на местности: в данных сайта отсутствует.',
    'amenity': None,
    'was:amenity': 'fast_food'
}


def dataset(fileobj):
    def parse_hours(s):
        s = re.sub('^зал:? *', '', s.lower())
        s = s.replace('<br />', ';').replace('<br>', ';').replace('\n', ';').replace(' ', '').replace(',', ';').replace('–', '-')
        s = s.replace('-00:', '-24:')
        weekdays = {k: v for k, v in map(lambda x: x.split(), 'пн Mo,вт Tu,ср We,чт Th,пт Fr,сб Sa,вс Su'.split(','))}
        if s == 'круглосуточно':
            return '24/7'
        parts = s.split(';')
        WEEKDAY_PATH = '(?:пн|вт|ср|чт|пт|сб|вск?)'
        result = []
        found_allweek = False
        for p in parts:
            if not p:
                continue
            m = re.match(r'^('+WEEKDAY_PATH+'(?:[-,]'+WEEKDAY_PATH+')*)?с?(\d?\d[:.]\d\d-\d?\d[:.]\d\d)$', p)
            if not m:
                # Disregarding other parts
                return None
            times = re.sub('(^|-)(\d:)', r'\g<1>0\g<2>', m[2].replace('.', ':'))
            if m[1]:
                wd = m[1].replace('вск', 'вс')
                for k, v in weekdays.items():
                    wd = wd.replace(k, v)
            else:
                found_allweek = True
                wd = 'Mo-Su'
            result.append(wd + ' ' + times)
        if not result or (found_allweek and len(result) > 1):
            return None
        return '; '.join(result)

    def parse_phone(s):
        s = s.replace('(', '').replace(')', '').replace('-', '')
        s = s.replace(' доб. ', '-')
        return s

    notes = {
        172: 'Подвинуть на второй терминал',
        25: 'Подвинуть в ЮниМолл',
        133: 'Передвинуть в Парк №1: https://prnt.sc/gtlwjs',
        471: 'Передвинуть в ТЦ Балканский 6, самый северный, где кино',
        234: 'Передвинуть на север, в дом 7',
        111: 'Сдвинуть в здание',
        59: 'Сдвинуть в торговый центр севернее',
        346: 'Передвинуть к кафе',

    }
    source = json.load(codecs.getreader('utf-8')(fileobj))
    data = []
    for el in source:
        gid = int(el['origID'])
        tags = {
            'amenity': 'fast_food',
            'name': 'Бургер Кинг',
            'name:ru': 'Бургер Кинг',
            'name:en': 'Burger King',
            'ref': gid,
            'cuisine': 'burger',
            'takeaway': 'yes',
            'wikipedia:brand': 'ru:Burger King',
            'wikidata:brand': 'Q177054',
            'contact:website': 'https://burgerking.ru/',
            'contact:email': el['email'],
            'contact:phone': parse_phone(el['tel']),
            'opening_hours': parse_hours(el['opened'])
        }
        if gid in notes:
            tags['fixme'] = notes[gid]
        if el['is_wifi']:
            tags['internet_access'] = 'wlan'
            tags['internet_access:fee'] = 'no'
        else:
            tags['internet_access'] = 'no'
        data.append(SourcePoint(gid, float(el['lat']), float(el['lng']), tags))
    return data
