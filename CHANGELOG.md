# OSM Conflator Change Log

## master branch

## 1.4.1

_Released 2019-06-04_

* Fixed an error when the query is pure regexp and it did not match anything.

## 1.4.0

_Released 2018-05-30_

* Refactored `conflate.py` into seven smaller files.
* Added a simple kd-tree based geocoder for countries and regions. Controlled by the `regions` parameter in a profile.
* You can filter by regions using `-r` argument or `"regions"` list in an audit file.
* Using the new `nwr` query type of Overpass API.
* Reduced default `max_request_boxes` to four.
* New argument `--alt-overpass` to use Kumi Systems' server (since the main one is blocked in Russia).
* Better handling of server runtime errors.
* Find matches in OSM with `--list <result.csv>`.
* Control number of nearest points to check for matches with `nearest_points` profile parameter.
* When you have dataset ID in an URL or other tag, use `find_ref` profile function to match on it.

## 1.3.3

_Released 2018-04-26_

* Fixed processing of `''` tag value.
* More that 3 duplicate points in a single place are processed correctly.
* Now you can `yield` points from a profile instead of making a list.
* Not marking nodes with `move` in the audit file as modified, unless we move them.

## 1.3.2

_Released 2018-04-19_

* Fixed bug in categories building.
* Fixed threshold for tags in duplicates check.
* Now the script prints "Done" when finished, to better measure time.

## 1.3.1

_Released 2018-03-20_

* "Similar tags" now means at least 66% instead of 50%.
* Instead of removing all duplicates, conflating them and removing only unmatched.

## 1.3.0

_Released 2018-03-15_

* Support for categories: `category_tag` and `categories` parameters in a profile.
* LibOsmium-based C++ filtering script for categories.
* More than one tag value works as "one of": `[('amenity', 'cafe', 'restaurant')]`.
* Query can be a list of queries, providing for "OR" clause. An example:

    `[[('amenity', 'swimming_pool')], [('leisure', 'swimming_pool')]]`

* Parameters for profiles, using `-p` argument.
* No more default imports solely for profiles, import `zipfile` youself now.
* Remarks for source points, thanks [@nixi](https://github.com/hixi).
* Better error message for Overpass API timeouts.
* Lifecycle prefixes are conflated, e.g. `amenity=*` and `was:amenity=*`.
* Dataset is checked for duplicates, which are reported (see `-d`) and removed.
* Support GeoJSON input (put identifiers into `id` property).

## 1.2.3

_Released 2017-12-29_

* Fix error in applying audit json after conflating `contact:` namespace.

## 1.2.2

_Released 2017-12-27_

* Addr:full tag is not set when addr:housenumber is present.
* Whitespace is stripped from tag values in a dataset.
* Conflate `contact:` namespace.

## 1.2.1

_Released 2017-12-20_

* Support force creating points with `audit['create']`.
* Fix green colour for created points in JSON.
* Make `--output` optional and remove the default.

## 1.2.0

_Released 2017-11-23_

* Checking moveability for json output (`-m`) for cf_audit.
* Support for cf_audit json (`-a`).

## 1.1.0

_Released 2017-10-06_

* Use `-v` for debug messages and `-q` to suppress informational messages.
* You can run `conflate/conflate.py` as a script, again.
* Profiles: added "override" dict with dataset id → OSM POI name or id like 'n12345'.
* Profiles: added "matched" function that returns `False` if an OSM point should not be matched to dataset point (fixes [#6](https://github.com/mapsme/osm_conflate/issues/6)).
* Profiles: `master_tags` is no longer mandatory.
* If no `master_tags` specified in a profile, all tags are now considered non-master.
* When a tag value was `None`, the tag was deleted on object modification. That should be done only on retagging non-matched objects.
* OSM objects filtering failed when a query was a string.

## 1.0.0

_Released 2017-06-07_

The initial PyPi release with all the features.
