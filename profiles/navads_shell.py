# This profile reads a prepared JSON, thus no "dataset" function

# Value for the changeset "source" tag
source = 'Navads'
# Keeping identifiers in a "ref:navads_shell" tag
dataset_id = 'navads_shell'
# Overpass API query is a simple [amenity="fuel"]
query = [('amenity', 'fuel')]
# These tag values override values on OSM objects
master_tags = ('brand', 'addr:postcode', 'phone', 'opening_hours')
# Looking at most 50 meters around a dataset point
max_distance = 50


def format_phone(ph):
    if ph and len(ph) == 13 and ph[:3] == '+44':
        if (ph[3] == '1' and ph[4] != '1' and ph[5] != '1') or ph[3:7] == '7624':
            return ' '.join([ph[:3], ph[3:7], ph[7:]])
        elif ph[3] in ('1', '3', '8', '9'):
            return ' '.join([ph[:3], ph[3:6], ph[6:9], ph[9:]])
        else:
            return ' '.join([ph[:3], ph[3:5], ph[5:9], ph[9:]])
    return ph


# Tag transformation
transform = {
    # Just add this tag
    'amenity': 'fuel',
    # Rename key
    'postal_code': '>addr:postcode',
    # Use a function to transform a value
    'phone': format_phone,
    # Remove this tag
    'name': '-'
}

# Example JSON line:
#
# {
#   "id": "NVDS298-10018804",
#   "lat": 51.142491,
#   "lon": -0.074893,
#   "tags": {
#     "name": "Shell",
#     "brand": "Shell",
#     "addr:street": "Snow Hill",
#     "postal_code": "RH10 3EQ",
#     "addr:city": "Crawley",
#     "phone": "+441342718750",
#     "website": "http://www.shell.co.uk",
#     "operator": "Shell",
#     "opening_hours": "24/7",
#     "amenity": "fuel"
#   }
# }
