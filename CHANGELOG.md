# OSM Conflator Change Log

## master branch

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
