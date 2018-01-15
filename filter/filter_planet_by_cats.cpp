/*
    Filters a planet file by categories and location.

    Serves as a replacement for Overpass API for the OSM Conflator.
    Takes two parameters: a list of coordinates and categories prepared by
    conflate.py and an OSM PBF/XML file. Prints an OSM XML file with
    objects that will then be conflated with the external dataset.
    Either specify that XML file name as the third parameter, or redirect
    the output.

    Based on the osmium_amenity_list.cpp from libosmium.

    Published under Apache Public License 2.0.

    Written by Ilya Zverev for MAPS.ME.
*/

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <fstream>
#include <string>
#include <map>

#include <osmium/geom/coordinates.hpp>
#include <osmium/handler/node_locations_for_ways.hpp>
#include <osmium/index/map/flex_mem.hpp>
#include <osmium/io/any_input.hpp>
#include <osmium/io/xml_output.hpp>
#include <osmium/relations/relations_manager.hpp>
#include <osmium/visitor.hpp>

#include "RTree.h"
#include "xml_centers_output.hpp"

using index_type = osmium::index::map::FlexMem<osmium::unsigned_object_id_type,
                                               osmium::Location>;
using location_handler_type = osmium::handler::NodeLocationsForWays<index_type>;

bool AppendToVector(uint16_t cat_id, void *vec) {
  static_cast<std::vector<uint16_t>*>(vec)->push_back(cat_id);
  return true;
}

class AmenityHandler : public osmium::handler::Handler {

  constexpr static double kSearchRadius = 0.0001; // ~1 km TODO! revert to 0.01

  typedef RTree<uint16_t, int32_t, 2, double> DatasetTree;
  typedef std::vector<std::vector<std::string>> TQuery;
  typedef std::vector<TQuery> TCategory;

  DatasetTree m_tree;
  osmium::io::xmlcenters::XMLCentersOutput m_centers;
  std::map<uint16_t, std::vector<TQuery>> m_categories;
  std::map<uint16_t, std::string> m_category_names;

  void print_object(const osmium::OSMObject &obj,
                    const osmium::Location &center) {
    std::cout << m_centers.apply(obj, center);
  }

  // Calculate the center point of a NodeRefList.
  osmium::Location calc_center(const osmium::NodeRefList &nr_list) {
    int64_t x = 0;
    int64_t y = 0;

    for (const auto &nr : nr_list) {
      x += nr.x();
      y += nr.y();
    }

    x /= nr_list.size();
    y /= nr_list.size();

    return osmium::Location{x, y};
  }

  bool TestTags(osmium::TagList const & tags, TQuery const & query) {
    for (auto const & pair : query) {
      // TODO
    }
    return true;
  }

  bool IsEligible(const osmium::Location & loc, osmium::TagList const & tags) {
    if (tags.empty())
      return false;

    int32_t radius = osmium::Location::double_to_fix(kSearchRadius);
    int32_t min[] = {loc.x() - radius, loc.y() - radius};
    int32_t max[] = {loc.x() + radius, loc.y() + radius};
    std::vector<uint16_t> found;
    if (!m_tree.Search(min, max, &AppendToVector, &found))
      return false;
    for (uint16_t cat_id : found)
      for (TQuery query : m_categories[cat_id])
        if (TestTags(tags, query))
          return true;
    return false;
  }

  void SplitTrim(std::string const & s, char delimiter, std::size_t limit, std::vector<std::string> & target) {
    target.clear();
    std::size_t start = 0, end = 0;
    while (start < s.length()) {
      end = s.find(delimiter, start);
      if (end == std::string::npos || target.size() == limit)
        end = s.length();
      while (start < end && std::isspace(s[start]))
        start++;

      std::size_t tmpend = end - 1;
      while (tmpend > start && std::isspace(s[tmpend]))
        tmpend++;
      target.push_back(s.substr(start, tmpend - start + 1));
      start = end + 1;
    }
  }

  TQuery ParseQuery(std::string const & query) {
    TQuery q;
    std::vector<std::string> parts;
    SplitTrim(query, '|', 100, parts);
    for (std::string const & part : parts) {
      std::vector<std::string> keys;
      SplitTrim(part, '=', 100, keys);
      if (keys.size() > 0)
          q.push_back(keys);
    }
    return q;
  }

  void LoadCategories(const char *filename) {
    std::ifstream infile(filename);
    std::string line;
    std::vector<std::string> parts;
    bool parsingPoints = false;
    while (std::getline(infile, line)) {
      if (!parsingPoints) {
        if (!line.size())
          parsingPoints = true;
        else {
          SplitTrim(line, ',', 3, parts); // cat_id, name, query
          uint16_t cat_id = std::stoi(parts[0]);
          m_category_names[cat_id] = parts[1];
          m_categories[cat_id].push_back(ParseQuery(parts[2]));
        }
      } else {
        SplitTrim(line, ',', 3, parts); // lon, lat, cat_id
        const osmium::Location loc(std::stod(parts[0]), std::stod(parts[1]));
        int32_t coords[] = {loc.x(), loc.y()};
        uint16_t cat_id = std::stoi(parts[2]);
        m_tree.Insert(coords, coords, cat_id);
      }
    }
  }

public:
  AmenityHandler(const char *categories) {
    LoadCategories(categories);
  }

  void node(osmium::Node const & node) {
    if (IsEligible(node.location(), node.tags())) {
      print_object(node, node.location());
    }
  }

  void way(osmium::Way const & way) {
    if (!way.is_closed())
      return;

    int64_t x = 0, y = 0, cnt = 0;
    for (const auto& node_ref : way.nodes()) {
        if (node_ref.location()) {
            x += node_ref.x();
            y += node_ref.y();
            cnt++;
        }
    }
    if (!cnt)
      return;

    const osmium::Location center(x / cnt, y / cnt);
    if (IsEligible(center, way.tags())) {
      print_object(way, center);
    }
  }

  void multi(osmium::Relation const & rel, osmium::Location const & center) {
    if (IsEligible(center, rel.tags())) {
      print_object(rel, center);
    }
  }

}; // class AmenityHandler

class AmenityRelationsManager : public osmium::relations::RelationsManager<AmenityRelationsManager, false, true, false> {

    AmenityHandler *m_handler;

public:

  AmenityRelationsManager(AmenityHandler & handler) :
      RelationsManager(),
      m_handler(&handler) {
  }

  bool new_relation(osmium::Relation const & rel) noexcept {
    const char *rel_type = rel.tags().get_value_by_key("type");
    return rel_type && !std::strcmp(rel_type, "multipolygon");
  }

  void complete_relation(osmium::Relation const & rel) {
    int64_t x = 0, y = 0, cnt = 0;
    for (auto const & member : rel.members()) {
        if (member.ref() != 0) {
            const osmium::Way* way = this->get_member_way(member.ref());
            for (const auto& node_ref : way->nodes()) {
                if (node_ref.location()) {
                    x += node_ref.x();
                    y += node_ref.y();
                    cnt++;
                }
            }
        }
    }
    if (cnt > 0)
        m_handler->multi(rel, osmium::Location{x / cnt, y / cnt});
  }
}; // class AmenityRelationsManager

int main(int argc, char *argv[]) {
  if (argc < 3) {
    std::cerr << "Usage: " << argv[0]
              << " <dataset.lst> <osmfile>\n";
    std::exit(1);
  }

  const osmium::io::File input_file{argv[2]};
  const osmium::io::File output_file{"", "osm"};

  AmenityHandler data_handler(argv[1]);
  AmenityRelationsManager manager(data_handler);
  osmium::relations::read_relations(input_file, manager);

  osmium::io::Header header;
  header.set("generator", argv[0]);
  osmium::io::Writer writer{output_file, header, osmium::io::overwrite::allow};

  index_type index;
  location_handler_type location_handler{index};
  location_handler.ignore_errors();
  osmium::io::Reader reader{input_file};

  osmium::apply(reader, location_handler, data_handler, manager.handler());

  std::cout.flush();
  reader.close();
  writer.close();
}
