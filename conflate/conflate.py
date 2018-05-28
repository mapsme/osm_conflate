#!/usr/bin/env python3
import argparse
import csv
import json
import logging
import os
import sys
from .geocoder import Geocoder
from .profile import Profile
from .conflator import OsmConflator, TITLE
from .dataset import (
    read_dataset,
    add_categories_to_dataset,
    transform_dataset,
    check_dataset_for_duplicates,
    add_regions,
)


def write_for_filter(profile, dataset, f):
    def query_to_tag_strings(query):
        if isinstance(query, str):
            raise ValueError('Query string for filter should not be a string')
        result = []
        if not isinstance(query[0], str) and isinstance(query[0][0], str):
            query = [query]
        for q in query:
            if isinstance(q, str):
                raise ValueError('Query string for filter should not be a string')
            parts = []
            for part in q:
                if len(part) == 1:
                    parts.append(part[0])
                elif part[1] is None or len(part[1]) == 0:
                    parts.append('{}='.format(part[0]))
                elif part[1][0] == '~':
                    raise ValueError('Cannot use regular expressions in filter')
                elif '|' in part[1] or ';' in part[1]:
                    raise ValueError('"|" and ";" symbols is not allowed in query values')
                else:
                    parts.append('='.join(part))
            result.append('|'.join(parts))
        return result

    def tags_to_query(tags):
        return [(k, v) for k, v in tags.items()]

    categories = profile.get('categories', {})
    p_query = profile.get('query', None)
    if p_query is not None:
        categories[None] = {'query': p_query}
    cat_map = {}
    i = 0
    try:
        for name, query in categories.items():
            for tags in query_to_tag_strings(query.get('query', tags_to_query(query.get('tags')))):
                f.write('{},{},{}\n'.format(i, name or '', tags))
            cat_map[name] = i
            i += 1
    except ValueError as e:
        logging.error(e)
        return False
    f.write('\n')
    for d in dataset:
        if d.category in cat_map:
            f.write('{},{},{}\n'.format(d.lon, d.lat, cat_map[d.category]))
    return True


def run(profile=None):
    parser = argparse.ArgumentParser(
        description='''{}.
        Reads a profile with source data and conflates it with OpenStreetMap data.
        Produces an JOSM XML file ready to be uploaded.'''.format(TITLE))
    if not profile:
        parser.add_argument('profile', type=argparse.FileType('r'),
                            help='Name of a profile (python or json) to use')
    parser.add_argument('-i', '--source', type=argparse.FileType('rb'),
                        help='Source file to pass to the profile dataset() function')
    parser.add_argument('-a', '--audit', type=argparse.FileType('r'),
                        help='Conflation validation result as a JSON file')
    parser.add_argument('-o', '--output', type=argparse.FileType('w'),
                        help='Output OSM XML file name')
    parser.add_argument('-p', '--param',
                        help='Optional parameter for the profile')
    parser.add_argument('--osc', action='store_true',
                        help='Produce an osmChange file instead of JOSM XML')
    parser.add_argument('--osm',
                        help='Instead of querying Overpass API, use this unpacked osm file. ' +
                        'Create one from Overpass data if not found')
    parser.add_argument('-c', '--changes', type=argparse.FileType('w'),
                        help='Write changes as GeoJSON for visualization')
    parser.add_argument('-m', '--check-move', action='store_true',
                        help='Check for moveability of modified modes')
    parser.add_argument('-f', '--for-filter', type=argparse.FileType('w'),
                        help='Prepare a file for the filtering script')
    parser.add_argument('-l', '--list', type=argparse.FileType('w'),
                        help='Print a CSV list of matches')
    parser.add_argument('-d', '--list_duplicates', action='store_true',
                        help='List all duplicate points in the dataset')
    parser.add_argument('-r', '--regions',
                        help='Conflate only points with regions in this comma-separated list')
    parser.add_argument('--alt-overpass', action='store_true',
                        help='Use an alternate Overpass API server')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Display debug messages')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Do not display informational messages')
    options = parser.parse_args()

    if (not options.output and not options.changes and
            not options.for_filter and not options.list):
        parser.print_help()
        return

    if options.verbose:
        log_level = logging.DEBUG
    elif options.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if not profile:
        logging.debug('Loading profile %s', options.profile)
    profile = Profile(profile or options.profile, options.param)

    audit = None
    if options.audit:
        audit = json.load(options.audit)

    geocoder = Geocoder(profile.get_raw('regions'))
    if options.regions:
        geocoder.set_filter(options.regions)
    elif audit and audit.get('regions'):
        geocoder.set_filter(audit.get('regions'))

    dataset = read_dataset(profile, options.source)
    if not dataset:
        logging.error('Empty source dataset')
        sys.exit(2)
    transform_dataset(profile, dataset)
    add_categories_to_dataset(profile, dataset)
    check_dataset_for_duplicates(profile, dataset, options.list_duplicates)
    add_regions(dataset, geocoder)
    logging.info('Read %s items from the dataset', len(dataset))

    if options.for_filter:
        if write_for_filter(profile, dataset, options.for_filter):
            logging.info('Prepared data for filtering, exitting')
        return

    conflator = OsmConflator(profile, dataset, audit)
    conflator.geocoder = geocoder
    if options.alt_overpass:
        conflator.set_overpass('alt')
    if options.osm and os.path.exists(options.osm):
        with open(options.osm, 'r') as f:
            conflator.parse_osm(f)
    else:
        conflator.download_osm()
        if len(conflator.osmdata) > 0 and options.osm:
            with open(options.osm, 'w') as f:
                f.write(conflator.backup_osm())
    logging.info('Downloaded %s objects from OSM', len(conflator.osmdata))

    conflator.match()

    if options.output:
        diff = conflator.to_osc(not options.osc)
        options.output.write(diff)

    if options.changes:
        if options.check_move:
            conflator.check_moveability()
        fc = {'type': 'FeatureCollection', 'features': conflator.changes}
        json.dump(fc, options.changes, ensure_ascii=False, sort_keys=True, indent=1)

    if options.list:
        writer = csv.writer(options.list)
        writer.writerow(['ref', 'osm_type', 'osm_id', 'lat', 'lon', 'action'])
        for row in conflator.matches:
            writer.writerow(row)

    logging.info('Done')
