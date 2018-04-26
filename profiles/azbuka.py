#!/usr/bin/env python3
import conflate
import requests
import logging
import re
from io import BytesIO
from yandex_parser import parse_feed


class Profile:
    source = 'Азбука Вкуса'
    dataset_id = 'av'
    query = [('shop', 'convenience', 'supermarket', 'wine', 'alcohol')]
    master_tags = ('operator', 'shop', 'opening_hours', 'name', 'contact:website', 'contact:phone')
    download_url = 'https://av.ru/yandex/supermarket.xml'
    bounded_update = True

    def matches(osmtags, avtags):
        if 'Энотека' in avtags['name']:
            return osmtags.get('shop') in ('wine', 'alcohol')
        name = osmtags.get('name')
        if osmtags.get('shop') not in ('convenience', 'supermarket'):
            return False
        if not name or re.search(r'AB|АВ|Азбука|Daily', name, re.I):
            return True
        if name.upper() in ('SPAR', 'СПАР') or 'континент' in name.lower():
            return True
        return False

    def dataset(fileobj):
        data = []
        other_urls = [
            None,
            'http://av.ru/yandex/market.xml',
            'http://av.ru/yandex/daily.xml',
            'http://av.ru/yandex/enoteka.xml',
        ]
        for url in other_urls:
            if url:
                r = requests.get(url)
                if r.status_code != 200:
                    logging.error('Could not download source data: %s %s', r.status_code, r.text)
                    return None
                f = BytesIO(r.content)
            else:
                f = fileobj
            for c in parse_feed(f):
                name = next(iter(c.name.values()))
                tags = {
                    'name': name,
                    'operator': 'ООО «Городской супермаркет»',
                    'contact:phone': '; '.join(c.phones) or None,
                    'contact:website': c.url_add,
                    'opening_hours': c.opening_hours,
                }
                if 'Энотека' in name:
                    tags['shop'] = 'wine'
                elif 'Daily' in name:
                    tags['shop'] = 'convenience'
                else:
                    tags['shop'] = 'supermarket'
                data.append(conflate.SourcePoint(c.id, c.lat, c.lon, tags))
        return data


if __name__ == '__main__':
    conflate.run(Profile)
