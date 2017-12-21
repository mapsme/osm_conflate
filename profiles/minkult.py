import json
import logging
import requests
import codecs


# Reading the dataset passport to determine an URL of the latest dataset version
def download_url(dataset_id='7705851331-museums'):
    r = requests.get('http://opendata.mkrf.ru/opendata/{}/meta.json'.format(dataset_id))
    if r.status_code != 200 or len(r.content) == 0:
        logging.error('Could not get URL for dataset: %s %s', r.status_code, r.text)
        logging.error('Please check http://opendata.mkrf.ru/opendata/{}'.format(dataset_id))
        return None
    result = r.json()
    latest = result['data'][-1]
    logging.info('Downloading %s from %s', result['title'], latest['created'])
    return latest['source']

source = 'opendata.mkrf.ru'
dataset_id = 'mkrf_museums'
query = [('tourism', 'museum')]
max_distance = 300
master_tags = ('official_name', 'phone', 'opening_hours', 'website')


def dataset(fileobj):
    def make_wd_ranges(r):
        """Converts e.g. [0,1,4] into 'Mo-Tu, Fr'."""
        wd = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
        res = wd[r[0]]
        in_range = False
        for i in range(1, len(r)+1):
            if i < len(r) and r[i] == r[i-1] + 1:
                in_range = True
            else:
                if in_range:
                    res += '-' + wd[r[i-1]]
                    in_range = False
                if i < len(r):
                    res += ', ' + wd[r[i]]
        return res

    def parse_hours(h):
        """Receives a dict {'0': {'from': '10:00:00', 'to': '18:00:00'}, ...}
        and returns a proper opening_hours value."""
        days = {}
        for wd, d in h.items():
            if not d['from']:
                continue
            for i in ('from', 'to'):
                d[i] = d[i][:5]
            if d['to'] == '00:00':
                d['to'] = '24:00'
            elif not d['to']:
                d['to'] = '19:00+'
            k = '{}-{}'.format(d['from'], d['to'])
            if k not in days:
                days[k] = set()
            days[k].add(int(wd))
        days2 = {}
        for op, d in days.items():
            days2[tuple(sorted(d))] = op
        res = []
        for d in sorted(days2.keys(), key=lambda x: min(x)):
            res.append(' '.join([make_wd_ranges(d), days2[d]]))
        return '; '.join(res)

    def wrap(coord, absmax):
        if coord < -absmax:
            return coord + absmax * 2
        if coord > absmax:
            return coord - absmax * 2
        return coord

    def format_phone(ph):
        if ph and len(ph) == 11 and ph[0] == '7':
            return '+7 {} {}-{}-{}'.format(ph[1:4], ph[4:7], ph[7:9], ph[9:])
        return ph

    source = json.load(codecs.getreader('utf-8')(fileobj))
    data = []
    for el in source:
        d = el['data']['general']
        gid = d['id']
        lon = wrap(d['address']['mapPosition']['coordinates'][1], 180)
        lat = d['address']['mapPosition']['coordinates'][0]
        tags = {
            'tourism': 'museum',
            'name': d['name'],
            'official_name': d['name'],
            'image': d['image']['url'],
            'operator': d['organization']['name'],
            'addr:full': '{}, {}'.format(d['locale']['name'], d['address']['street']),
        }
        if tags['operator'] == tags['name']:
            del tags['operator']
        if d.get('workingSchedule'):
            tags['opening_hours'] = parse_hours(d['workingSchedule'])
        if 'email' in d['contacts']:
            tags['email'] = d['contacts']['email']
        if 'website' in d['contacts']:
            tags['website'] = d['contacts']['website']
            if tags['website'].endswith('.ru'):
                tags['website'] += '/'
        if 'phones' in d['contacts'] and d['contacts']['phones']:
            tags['phone'] = format_phone(d['contacts']['phones'][0]['value'])
        data.append(SourcePoint(gid, lat, lon, tags))
    return data
