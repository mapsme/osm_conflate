# This profile requires lxml package
import logging
import re

# A web page with a list of shops in Moscow. You can replace it with one for another city
download_url = 'https://www.auchan.ru/ru/moscow/'
source = 'auchan.ru'
# Not adding a ref:auchan tag, since we don't have good identifiers
no_dataset_id = True
# Using a name query with regular expressions
query = [('shop', '~supermarket|mall'), ('name', '~Ашан|АШАН')]
master_tags = ('name', 'opening_hours', 'phone', 'website')
# Empty dict so we don't add a fixme tag to unmatched objects
tag_unmatched = {}
# Coordinates are VERY approximate, so increasing max distance to ~1 km
max_distance = 0.01

# For some reason, functions here cannot use variables defined above
# And defining them as "global" moves these from locals() to globals()
download_url_copy = download_url
def dataset(fileobj):
    def parse_weekdays(s):
        weekdays = {k: v for k, v in map(lambda x: x.split(), 'пн Mo,вт Tu,ср We,чт Th,пт Fr,сб Sa,вс Su'.split(','))}
        s = s.replace(' ', '').lower().replace('c', 'с')
        if s == 'ежедневно' or s == 'пн-вс':
            return ''
        parts = []
        for x in s.split(','):
            p = None
            if x in weekdays:
                p = weekdays[x]
            elif '-' in x:
                m = re.match(r'(\w\w)-(\w\w)', x)
                if m:
                    pts = [weekdays.get(m.group(i), None) for i in (1, 2)]
                    if pts[0] and pts[1]:
                        p = '-'.join(pts)
            if p:
                parts.append(p)
            else:
                logging.warning('Could not parse opening hours: %s', s)
                return None
        return ','.join(parts)

    # We are parsing HTML, and for that we need an lxml package
    from lxml import html
    global download_url_copy
    h = html.fromstring(fileobj.read().decode('utf-8'))
    shops = h.find_class('shops-in-the-city-holder')[0]
    shops.make_links_absolute(download_url_copy)
    blocks = shops.xpath("//div[@class='mark-box'] | //ul[@class='shops-list']")
    name = None
    RE_GMAPS = re.compile(r'q=(-?[0-9.]+)\+(-?[0-9.]+)$')
    RE_OH = re.compile(r'(Ежедневно|(?:(?:Пн|Вт|Ср|Чт|Пт|Сб|В[сc])[, -]*)+)[ сc:]+(\d\d?[:.]\d\d)[- до]+(\d\d[.:]\d\d)', re.I)
    data = []
    for block in blocks:
        if block.get('class') == 'mark-box':
            name = block.xpath("strong[contains(@class, 'name')]/text()")[0].replace('АШАН', 'Ашан')
            logging.debug('Name: %s', name)
        elif block.get('class') == 'shops-list':
            for li in block:
                title = li.xpath("strong[@class='title']/a/text()")
                title = title[0].lower() if title else None
                website = li.xpath("strong[@class='title']/a/@href")
                website = website[0] if website else None
                addr = li.xpath("p[1]/text()")
                addr = addr[0].strip() if addr else None
                lat = None
                lon = None
                gmapslink = li.xpath(".//a[contains(@href, 'maps.google')]/@href")
                if gmapslink:
                    m = RE_GMAPS.search(gmapslink[0])
                    if m:
                        lat = float(m.group(1))
                        lon = float(m.group(2))
                opening_hours = []
                # Extract opening hours
                oh = ' '.join(li.xpath("p/text()"))
                for m in RE_OH.finditer(oh):
                    weekdays = parse_weekdays(m.group(1))
                    if weekdays is not None:
                        opening_hours.append('{}{:0>5s}-{:0>5s}'.format(
                            weekdays + ' ' if weekdays else '', m.group(2).replace('.', ':'), m.group(3).replace('.', ':')))
                logging.debug('Found title: %s, website: %s, opens: %s, coords: %s, %s', title, website, '; '.join(opening_hours) or None, lat, lon)
                if lat is not None and name is not None:
                    tags = {
                        'name': name,
                        'brand': 'Auchan',
                        'shop': 'supermarket',
                        'phone': '8-800-700-5-800',
                        'operator': 'ООО «АШАН»',
                        'opening_hours': '; '.join(opening_hours),
                        'addr:full': addr,
                        'website': website
                    }
                    data.append(SourcePoint(title, lat, lon, tags))
    return data
