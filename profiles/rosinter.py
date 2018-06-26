download_url = 'http://www.rosinter.ru/locator/RestaurantsFeed.aspx?city=all&location=&lang=ru&brand=all&cuisine=all&metro=&hasDelivery=&isCorporate='
source = 'Rosinter'
no_dataset_id = True
max_distance = 500
query = [('amenity', 'restaurant', 'cafe', 'bar', 'pub', 'fast_food')]
overpass_timeout = 1000
duplicate_distance = -1
nearest_points = 30
master_tags = ('name', 'phone', 'amenity')

types = {
    # substr: osm_substr, amenity, cuisine
    'Costa': ['costa', 'cafe', 'coffee_shop'],
    'IL': [('patio', 'патио'), 'restaurant', 'italian'],
    'TGI': [('tgi', 'friday'), 'restaurant', 'american'],
    'Бар и': ['гриль', 'restaurant', 'american'],
    'Макд': ['мак', 'fast_food', None],
    'Раша': ['мама', 'fast_food', 'russian'],
    'Планета': ['планета', 'restaurant', 'japanese'],
    'Шика': ['шика', 'restaurant', 'asian'],
    'Свои': ['сво', 'restaurant', None],
}


def matches(osmtags, ritags):
    global types
    rname = ritags['name']
    name = osmtags.get('name', '').lower()
    for k, v in types.items():
        if k in rname:
            if isinstance(v[0], str):
                return v[0] in name
            for n in v[0]:
                if n in name:
                    return True
            return False
    logging.error('Unknown rname value: %s', rname)
    return False


def dataset(f):
    global types
    from lxml import etree
    root = etree.parse(f).getroot()
    for el in root.find('Restaurants'):
        rid = el.find('id').text
        city = el.find('city').text
        if city in ('Прага', 'Будапешт', 'Варшава', 'Баку', 'Рига'):
            continue
        brand = el.find('brand').text
        if 'TGI' in brand:
            brand = 'TGI Fridays'
        elif 'СВОИ' in brand:
            brand = 'Свои'
        phone = el.find('telephone').text
        if phone:
            phone = phone.replace('(', '').replace(')', '')
        website = el.find('siteurl').text
        if website and 'il-patio' in website:
            website = 'http://ilpatio.ru'
        if 'Свои' in brand:
            website = 'http://restoransvoi.by'
        lat = float(el.find('latitude').text)
        lon = float(el.find('longitude').text)
        tags = {
            'amenity': 'restaurant',
            'name': brand,
            'phone': phone,
            'website': website,
        }
        address = el.find('address').text
        for k, v in types.items():
            if k in brand:
                tags['amenity'] = v[1]
                tags['cuisine'] = v[2]
        yield SourcePoint(
            rid, lat, lon, tags,
            remarks='Обязательно подвиньте точку!\nАдрес: ' + str(address))
