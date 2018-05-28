# Scripts

Here are some (one at the moment) scripts to prepare data for the conflator
or do stuff after conflating.

## pack_places.py

Prepares `places.bin` file for the geocoder. Requires three JSON files:

* places.json
* regions.json
* countries.json

These comprise the "places feed" and can be prepared using
[these scripts](https://github.com/mapsme/geocoding_data). You can
find a link to a ready-made feed in that repository.
