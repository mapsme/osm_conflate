# OSM Conflator Change Log

## master branch

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
