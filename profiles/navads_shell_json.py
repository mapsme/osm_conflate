source = 'Navads'
dataset_id = 'navads_shell'
query = [('amenity', 'fuel')]
master_tags = ('brand', 'phone', 'opening_hours')
max_distance = 50
max_request_boxes = 3


def dataset(fileobj):
    import json
    import codecs
    import re
    from collections import defaultdict

    def format_phone(ph):
        if ph and len(ph) == 13 and ph[:3] == '+44':
            if (ph[3] == '1' and ph[4] != '1' and ph[5] != '1') or ph[3:7] == '7624':
                return ' '.join([ph[:3], ph[3:7], ph[7:]])
            elif ph[3] in ('1', '3', '8', '9'):
                return ' '.join([ph[:3], ph[3:6], ph[6:9], ph[9:]])
            else:
                return ' '.join([ph[:3], ph[3:5], ph[5:9], ph[9:]])
        return ph

    def make_wd_ranges(r):
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
                    res += ',' + wd[r[i]]
        return res

    def parse_hours(h):
        if not h:
            return None
        WD = {x: i for i, x in enumerate([
            'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'
        ])}
        days = defaultdict(list)
        for d in h.split(';'):
            parts = re.findall(r'([A-Z]+)=([0-9:-]+)', d)
            if len(set([p[0] for p in parts])) != 1:
                raise Exception('Parts format fail: {}'.format(d))
            days[','.join([p[1] for p in parts])].append(WD[parts[0][0]])
        res = []
        for time, wd in sorted(days.items(), key=lambda x: min(x[1])):
            res.append(' '.join([make_wd_ranges(wd), time]))
        if res[0] == 'Mo-Su 00:00-23:59':
            return '24/7'
        return '; '.join(res).replace('23:59', '24:00')

    global re, defaultdict
    source = json.load(codecs.getreader('utf-8-sig')(fileobj))
    data = []
    for el in source['Locations']:
        if not el['location']:
            continue
        coords = [float(x) for x in el['location'].split(',')]
        tags = {
            'amenity': 'fuel',
            'brand': el['name'],
            'addr:postcode': el['address_zip'] or None,
            'phone': format_phone('+'+str(el['phone'])),
            'opening_hours': parse_hours(el['daily_hours']),
        }
        if (el['address_street'] and el['address_number'] and
                not re.search(r'^([ABCDM]\d+|Junction)', el['address_street']) and
                'Ln' not in el['address_street'] and 'A' not in el['address_number']):
            tags['addr:street'] = el['address_street']
            tags['addr:housenumber'] = el['address_number']
        data.append(SourcePoint(el['place_id'], coords[0], coords[1], tags))
    return data


# Example line of the source JSON:
#
# {
#   "place_id": "NVDS353-10019224",
#   "name": "Shell",
#   "category": "GAS_STATION",
#   "location": "54.978366,-1.57441",
#   "description": "",
#   "phone": 441912767084,
#   "address_street": "Shields Road",
#   "address_number": "308",
#   "address_city": "Newcastle-Upon-Tyne",
#   "address_zip": "NE6 2UU",
#   "address_country": "GB",
#   "website": "http://www.shell.co.uk/motorist/station-locator.html?id=10019224&modeselected=true",
#   "daily_hours": "MONDAY=00:00-23:59;TUESDAY=00:00-23:59;WEDNESDAY=00:00-23:59;THURSDAY=00:00-23:59;FRIDAY=00:00-23:59;SATURDAY=00:00-23:59;SUNDAY=00:00-23:59",
#   "brand": "Shell",
#   "is_deleted": false
# },
