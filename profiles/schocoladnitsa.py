download_url = 'http://new.shoko.ru/addresses/'
source = 'Шоколадница'
no_dataset_id = True
overpass_timeout = 600
max_distance = 250
max_request_boxes = 6
query = [('amenity',), ('name', '~Шоколадница')]
master_tags = ['amenity', 'name', 'name:ru', 'name:en', 'website', 'phone', 'opening_hours']


def dataset(fileobj):
    def parse_oh(s):
        if not s:
            return None
        olds = s
        if s.strip().lower() == 'круглосуточно':
            return '24/7'
        trans = {
            'будни': 'Mo-Fr',
            'суббота': 'Sa',
            'воскресенье': 'Su',
            'ежедневно': 'Mo-Su',
            'выходные': 'Sa-Su',
            'восерсенье': 'Su',
            'ежеденевно': 'Mo-Su',
            'пн-чтивс': 'Mo-Th,Su',
            'пн-чт,вс': 'Mo-Th,Su',
            'пт.-сб': 'Fr-Sa',
            'вск.-чт': 'Su-Th',
            'смаяпооктябрь': 'May-Oct',
            'ч.смаяпооктябрь': 'May-Oct',
            'сентября': 'May-Sep',
        }
        weekdays = {'пн': 'Mo', 'вт': 'Tu', 'ср': 'We', 'чт': 'Th', 'пт': 'Fr', 'сб': 'Sa', 'вс': 'Su'}
        if s == 'с 10 до 22' or s == 'с 10.00-22.00':
            s = '10:00 - 22:00'
        s = s.replace('круглосуточно', '00:00-24:00')
        s = s.replace('23,', '23:00')
        parts = []
        for m in re.finditer(r'([а-яА-Я ,.:\(\)-]+?)?(?:\sс)?\s*(\d?\d[:.]\d\d)(?: до |[^\w\d]+)(\d\d[:.]\d\d)', s):
            days = (m[1] or '').strip(' -.,:()').lower().replace(' ', '')
            m2 = re.match(r'^([б-ч]{2})\s?[,и-]\s?([б-ч]{2})$', days)
            if not days:
                days = 'Mo-Su'
            elif days in weekdays:
                days = weekdays[days]
            elif m2 and m2[1] in weekdays and m2[2] in weekdays:
                days = weekdays[m2[1]] + '-' + weekdays[m2[2]]
            else:
                if days not in trans:
                    logging.warn('Unknown days: %s', days)
                    continue
                days = trans[days]
            parts.append('{} {:0>5}-{}'.format(days, m[2].replace('.', ':'), m[3].replace('.', ':')))
        # logging.info('%s -> %s', olds, '; '.join(parts))
        if parts:
            return '; '.join(parts)
        return None

    from lxml import html
    import re
    import logging
    import phonenumbers
    h = html.fromstring(fileobj.read().decode('utf-8'))
    markers = h.get_element_by_id('markers')
    i = 0
    for m in markers:
        lat = m.get('data-lat')
        lon = m.get('data-lng')
        if not lat or not lon:
            continue
        oh = parse_oh(m.get('data-time'))
        phone = m.get('data-phone')
        if phone[:3] == '812':
            phone = '+7' + phone
        if ' 891' in phone:
            phone = phone[:phone.index(' 891')]
        if ' 8-91' in phone:
            phone = phone[:phone.index(' 8-91')]
        try:
            if phone == 'отключен' or not phone:
                phone = None
            else:
                parsed_phone = phonenumbers.parse(phone.replace(';', ',').split(',')[0], "RU")
        except:
            logging.info(phone)
            raise
        if phone is None:
            fphone = None
        else:
            fphone = phonenumbers.format_number(
                parsed_phone, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        tags = {
            'amenity': 'cafe',
            'name': 'Шоколадница',
            'name:ru': 'Шоколадница',
            'name:en': 'Shokoladnitsa',
            'website': 'http://shoko.ru',
            'cuisine': 'coffee_shop',
            'phone': fphone,
            'opening_hours': oh
        }
        i += 1
        yield SourcePoint(i, float(lat), float(lon), tags, remarks=m.get('data-title'))
