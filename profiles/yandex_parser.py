from lxml import etree
import logging
import re
import phonenumbers  # https://pypi.python.org/pypi/phonenumberslite


class Company:
    def __init__(self, cid):
        self.id = cid
        self.name = {}
        self.alt_name = {}
        self.address = {}
        self.country = {}
        self.address_add = {}
        self.opening_hours = None
        self.url = None
        self.url_add = None
        self.url_ext = None
        self.email = None
        self.rubric = []
        self.phones = []
        self.faxes = []
        self.photos = []
        self.lat = None
        self.lon = None
        self.other = {}


def parse_feed(f):
    def multilang(c, name):
        for el in company.findall(name):
            lang = el.get('lang', 'default')
            value = el.text
            if value and len(value.strip()) > 0:
                c[lang] = value.strip()

    def parse_subels(el):
        res = {}
        if el is None:
            return res
        for subel in el:
            name = subel.tag
            text = subel.text
            if text and text.strip():
                res[name] = text
        return res

    def parse_opening_hours(s):
        if 'углосуточн' in s:
            return '24/7'
        m = re.search(r'([01]?\d:\d\d).*?([12]?\d:\d\d)', s)
        if m:
            # TODO: parse weekdays
            start = m.group(1)
            start = re.sub(r'^(\d:)', r'0\1', start)
            end = m.group(2)
            end = re.sub(r'0?0:', '24:', end)
            return 'Mo-Su {}-{}'.format(start, end)
        # TODO
        return None

    xml = etree.parse(f).getroot()
    if xml.tag != 'companies':
        logging.error('Root node must be named "companies", not %s', xml.tag)
    for company in xml:
        if company.tag != 'company':
            logging.warn('Non-company in yandex xml: %s', company.tag)
            continue
        cid = company.find('company-id')
        if cid is None or not cid.text:
            logging.error('No id for a company')
            continue
        c = Company(cid.text.strip())
        multilang(c.name, 'name')
        multilang(c.alt_name, 'name-other')
        multilang(c.address, 'address')
        loc = {}
        multilang(loc, 'locality-name')
        if loc:
            for lng, place in loc.items():
                if lng in c.address:
                    c.address = place + ', ' + c.address
        multilang(c.address_add, 'address-add')
        multilang(c.country, 'country')
        coord = parse_subels(company.find('coordinates'))
        if 'lat' in coord and 'lon' in coord:
            c.lat = float(coord['lat'])
            c.lon = float(coord['lon'])
        else:
            logging.warn('No coordinates for %s', c.id)
            continue
        for ph in company.findall('phone'):
            phone = parse_subels(ph)
            if 'number' not in phone:
                continue
            parsed_phone = phonenumbers.parse(phone['number'], 'RU')
            number = phonenumbers.format_number(
                parsed_phone, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
            if 'ext' in phone:
                number += ' ext. ' + phone['ext']
            typ = phone.get('type', 'phone')
            if typ == 'fax':
                c.faxes.append(number)
            else:
                c.phones.append(number)
        email = company.find('email')
        if email is not None and email.text:
            c.email = email.text.strip()
        url = company.find('url')
        if url is not None and url.text:
            c.url = url.text.strip()
        url_add = company.find('add-url')
        if url_add is not None and url_add.text:
            c.url_add = url_add.text.strip()
        url_ext = company.find('info-page')
        if url_ext is not None and url_ext.text:
            c.url_ext = url_ext.text.strip()
        for rub in company.findall('rubric-rd'):
            if rub.text:
                c.rubric.append(int(rub.text.strip()))
        coh = company.find('working-time')
        if coh is not None and coh.text:
            c.opening_hours = parse_opening_hours(coh.text)
        photos = company.find('photos')
        if photos is not None:
            for photo in photos:
                if photo.get('type', 'interior') != 'food':
                    c.photos.append(photo.get('url'))
        for feat in company:
            if feat.tag.startswith('feature-'):
                name = feat.get('name', None)
                value = feat.get('value', None)
                if name is not None and value is not None:
                    if feat.tag == 'feature-boolean':
                        value = value == '1'
                    elif '-numeric' in feat.tag:
                        value = float(value)
                    c.other[name] = value
        yield c
