import logging
import json
import codecs
import requests
import kdtree
from io import BytesIO
from .data import SourcePoint


def read_dataset(profile, fileobj):
    """A helper function to call a "dataset" function in the profile.
    If the fileobj is not specified, tries to download a dataset from
    an URL specified in "download_url" profile variable."""
    if not fileobj:
        url = profile.get('download_url')
        if url is None:
            logging.error('No download_url specified in the profile, '
                          'please provide a dataset file with --source')
            return None
        r = requests.get(url)
        if r.status_code != 200:
            logging.error('Could not download source data: %s %s', r.status_code, r.text)
            return None
        if len(r.content) == 0:
            logging.error('Empty response from %s', url)
            return None
        fileobj = BytesIO(r.content)
    if not profile.has('dataset'):
        # The default option is to parse the source as a JSON
        try:
            data = []
            reader = codecs.getreader('utf-8')
            json_src = json.load(reader(fileobj))
            if 'features' in json_src:
                # Parse GeoJSON
                for item in json_src['features']:
                    if item['geometry'].get('type') != 'Point' or 'properties' not in item:
                        continue
                    # Get the identifier from "id", "ref", "ref*"
                    iid = item['properties'].get('id', item['properties'].get('ref'))
                    if not iid:
                        for k, v in item['properties'].items():
                            if k.startswith('ref'):
                                iid = v
                                break
                    if not iid:
                        continue
                    data.append(SourcePoint(
                        iid,
                        item['geometry']['coordinates'][1],
                        item['geometry']['coordinates'][0],
                        {k: v for k, v in item['properties'].items() if k != 'id'}))
            else:
                for item in json_src:
                    data.append(SourcePoint(item['id'], item['lat'], item['lon'], item['tags']))
            return data
        except Exception:
            logging.error('Failed to parse the source as a JSON')
    return list(profile.get(
        'dataset', args=(fileobj,),
        required='returns a list of SourcePoints with the dataset'))


def add_categories_to_dataset(profile, dataset):
    categories = profile.get('categories')
    if not categories:
        return
    tag = profile.get('category_tag')
    other = categories.get('other', {})
    for d in dataset:
        if tag and tag in d.tags:
            d.category = d.tags[tag]
            del d.tags[tag]
        if d.category:
            cat_tags = categories.get(d.category, other).get('tags', None)
            if cat_tags:
                d.tags.update(cat_tags)


def transform_dataset(profile, dataset):
    """Transforms tags in the dataset using the "transform" method in the profile
    or the instructions in that field in string or dict form."""
    transform = profile.get_raw('transform')
    if not transform:
        return
    if callable(transform):
        for d in dataset:
            transform(d.tags)
        return
    if isinstance(transform, str):
        # Convert string of "key=value|rule1|rule2" lines to a dict
        lines = [line.split('=', 1) for line in transform.splitlines()]
        transform = {l[0].strip(): l[1].strip() for l in lines}
    if not transform or not isinstance(transform, dict):
        return
    for key in transform:
        if isinstance(transform[key], str):
            transform[key] = [x.strip() for x in transform[key].split('|')]

    for d in dataset:
        for key, rules in transform.items():
            if not rules:
                continue
            value = None
            if callable(rules):
                # The value can be generated
                value = rules(None if key not in d.tags else d.tags[key])
                if value is None and key in d.tags:
                    del d.tags[key]
            elif not rules[0]:
                # Use the value of the tag
                if key in d.tags:
                    value = d.tags[key]
            elif not isinstance(rules[0], str):
                # If the value is not a string, use it
                value = str(rules[0])
            elif rules[0][0] == '.':
                # Use the value from another tag
                alt_key = rules[0][1:]
                if alt_key in d.tags:
                    value = d.tags[alt_key]
            elif rules[0][0] == '>':
                # Replace the key
                if key in d.tags:
                    d.tags[rules[0][1:]] = d.tags[key]
                    del d.tags[key]
            elif rules[0][0] == '<':
                # Replace the key, the same but backwards
                alt_key = rules[0][1:]
                if alt_key in d.tags:
                    d.tags[key] = d.tags[alt_key]
                    del d.tags[alt_key]
            elif rules[0] == '-':
                # Delete the tag
                if key in d.tags:
                    del d.tags[key]
            else:
                # Take the value as written
                value = rules[0]
            if value is None:
                continue
            if isinstance(rules, list):
                for rule in rules[1:]:
                    if rule == 'lower':
                        value = value.lower()
            d.tags[key] = value


def check_dataset_for_duplicates(profile, dataset, print_all=False):
    # First checking for duplicate ids and collecting tags with varying values
    ids = set()
    tags = {}
    found_duplicate_ids = False
    for d in dataset:
        if d.id in ids:
            found_duplicate_ids = True
            logging.error('Duplicate id {} in the dataset'.format(d.id))
        ids.add(d.id)
        for k, v in d.tags.items():
            if k not in tags:
                tags[k] = v
            elif tags[k] != '---' and tags[k] != v:
                tags[k] = '---'

    # And then for near-duplicate points with similar tags
    uncond_distance = profile.get('duplicate_distance', 1)
    diff_tags = [k for k in tags if tags[k] == '---']
    kd = kdtree.create(list(dataset))
    duplicates = set()
    group = 0
    for d in dataset:
        if d.id in duplicates:
            continue
        group += 1
        dups = kd.search_knn(d, 2)  # The first one will be equal to d
        if len(dups) < 2 or dups[1][0].data.distance(d) > profile.max_distance:
            continue
        for alt, _ in kd.search_knn(d, 20):
            dist = alt.data.distance(d)
            if alt.data.id != d.id and dist <= profile.max_distance:
                tags_differ = 0
                if dist > uncond_distance:
                    for k in diff_tags:
                        if alt.data.tags.get(k) != d.tags.get(k):
                            tags_differ += 1
                if tags_differ <= len(diff_tags) / 3:
                    duplicates.add(alt.data.id)
                    d.exclusive_group = group
                    alt.data.exclusive_group = group
                    if print_all or len(duplicates) <= 5:
                        is_duplicate = tags_differ <= 1
                        logging.error('Dataset points %s: %s and %s',
                                      'duplicate each other' if is_duplicate else 'are too similar',
                                      d.id, alt.data.id)
    if duplicates:
        logging.error('Found %s duplicates in the dataset', len(duplicates))
    if found_duplicate_ids:
        raise KeyError('Cannot continue with duplicate ids')


def add_regions(dataset, geocoder):
    if not geocoder.enabled:
        return
    if geocoder.filter:
        logging.info('Geocoding and filtering points')
    else:
        logging.info('Geocoding points')
    for i in reversed(range(len(dataset))):
        region, present = geocoder.find(dataset[i])
        if not present:
            del dataset[i]
        else:
            dataset[i].region = region
