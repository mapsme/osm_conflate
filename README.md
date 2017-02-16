# OSM Conflator

This is a script for merging points from some third-party source with OpenStreetMap data.
Please make sure the license allows that. After merging and uploading, the data can be updated.

## Installation

Clone this repository, and from inside it run `pip install -r requirements.txt`.

## Profiles

Each source should have a profile. It is a python script with variables configuring
names, tags and processing. See heavily commented examples in the `profiles` directory.

## Usage

For a simplest case, run:

    ./conflate.py <profile.py>

You might want to add `-v` to get status messages, and other arguments to pass a dataset file
or write the resulting osmChange somewhere. Run `./conflate.py -h` to see a list of arguments.

## Uploading to OpenStreetMap

It is recommended to open the resulting file in the JOSM editor and manually check the changes.
Alternatively, you can use [bulk_upload.py](https://wiki.openstreetmap.org/wiki/Bulk_upload.py)
to upload a change file from the command line.

## License

Written by Ilya Zverev for MAPS.ME. Published under the Apache 2.0 license.
