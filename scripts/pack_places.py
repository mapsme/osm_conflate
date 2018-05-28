#!/usr/bin/env python3
import json
import struct
import os
import sys


def pack_coord(coord):
    data = struct.pack('<l', round(coord * 10000))
    return data[:-1]

if len(sys.argv) < 2:
    path = '.'
else:
    path = sys.argv[1]

with open(os.path.join(path, 'regions.json'), 'r') as f:
    regions = [(r, int(rid)) for rid, r in json.load(f).items() if r.get('iso')]
    reg_idx = {regions[i][1]: i for i in range(len(regions))}
with open(os.path.join(path, 'countries.json'), 'r') as f:
    countries = [(r, int(rid)) for rid, r in json.load(f).items() if r.get('iso')]
    c_idx = {countries[i][1]: i for i in range(len(countries))}
with open(os.path.join(path, 'places.json'), 'r') as f:
    places = json.load(f)

out = open('places.bin', 'wb')
out.write(struct.pack('B', len(countries)))
for c, _ in countries:
    out.write(struct.pack('2s', c['iso'].encode('ascii')))
out.write(struct.pack('<h', len(regions)))
for r, _ in regions:
    rname = r['iso'].encode('ascii')
    out.write(struct.pack('B', len(rname)))
    out.write(rname)
for pl in places.values():
    if pl['country'] not in c_idx:
        continue
    out.write(pack_coord(pl['lon']))
    out.write(pack_coord(pl['lat']))
    out.write(struct.pack('B', c_idx[pl['country']]))
    out.write(struct.pack('<h', reg_idx.get(pl.get('region'), -1)))
