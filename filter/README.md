# Filtering OSM by external dataset

When you got points of multiple categories, an Overpass API request may fail
from the number of query clauses. For that, you would need to filter the planet
file yourself. First, prepare a list of categories and dataset points:

    conflate.py profile.py -f points.lst

Then compile the filtering tool:

    mkdir build
    cmake ..
    make

Download a planet file or an extract for the country of import, update it to the minute,
and feed it to the filtering tool:

    ./filter_planet_by_cats points.lst planet-latest.osm.pbf > filtered.osm

This will take an hour or two. The resulting OSM file should be used as an input to
the conflation tool:

    conflate.py profile.py --osm filtered.osm -c changes.json

## Authors and License

The `filter_planet_by_cats` script was written by Ilya Zverev for MAPS.ME and
published under Apache License 2.0.

The `xml_centers_output.hpp` and `*.cmake` files are based on
[libosmium](https://github.com/osmcode/libosmium) code and hence published
under the Boost License terms.

`RTree.h` is under public domain, downloaded from
[this repository](https://github.com/nushoin/RTree).
