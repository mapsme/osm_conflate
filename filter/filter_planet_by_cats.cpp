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

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>

#include <osmium/area/assembler.hpp>
#include <osmium/area/multipolygon_manager.hpp>
#include <osmium/geom/coordinates.hpp>
#include <osmium/handler/node_locations_for_ways.hpp>
#include <osmium/index/map/flex_mem.hpp>
#include <osmium/io/any_input.hpp>
#include <osmium/io/xml_output.hpp>
#include <osmium/visitor.hpp>

#include "RTree.h"

using index_type = osmium::index::map::FlexMem<osmium::unsigned_object_id_type,
                                               osmium::Location>;
using location_handler_type = osmium::handler::NodeLocationsForWays<index_type>;

constexpr double kSearchRadius = 0.01; // ~1 km

class AmenityHandler : public osmium::handler::Handler {

  typedef RTree<uint16_t, int32_t, 2, double> DatasetTree;
  DatasetTree m_tree;

  void print_object(const osmium::OSMObject &obj,
                    const osmium::Location &center) {
    // TODO
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

  bool eligible(const osmium::Location &coord, osmium::TagList const &tags) {
    // TODO: find all points in a certain radius around coord
    // TODO: test tags for each of these points on tags
    return true; // TODO: change default to false
  }

  osmium::io::Writer &m_writer;

  void LoadCategories(const char *filename) {
    // TODO: read categories list and make an kd-tree of these.
  }

public:
  AmenityHandler(const char *categories, osmium::io::Writer &writer)
      : m_writer(writer) {
    LoadCategories(categories);
  }

  void node(const osmium::Node &node) {
    if (eligible(node.location(), node.tags())) {
      print_object(node, node.location());
    }
  }

  void area(const osmium::Area &area) {
    const auto center = calc_center(*area.cbegin<osmium::OuterRing>());
    if (eligible(center, area.tags())) {
      print_object(area, center);
    }
  }

}; // class AmenityHandler

int main(int argc, char *argv[]) {
  if (argc < 3) {
    std::cerr << "Usage: " << argv[0]
              << " <dataset.lst> <osmfile> [<output.xml>]\n";
    std::exit(1);
  }

  const osmium::io::File input_file{argv[2]};
  const osmium::io::File output_file{argc > 3 ? argv[3] : "", "osm"};

  std::cerr << "Pass 1/2: Assembling multipolygons...\n";
  osmium::area::Assembler::config_type assembler_config;
  assembler_config.create_empty_areas = false;
  osmium::area::MultipolygonManager<osmium::area::Assembler> mp_manager{
      assembler_config};
  osmium::relations::read_relations(input_file, mp_manager);

  osmium::io::Header header;
  header.set("generator", argv[0]);
  osmium::io::Writer writer{output_file, header, osmium::io::overwrite::allow};
  AmenityHandler data_handler(argv[1], writer);

  std::cerr << "Pass 2/2: Filtering points...\n";
  index_type index;
  location_handler_type location_handler{index};
  location_handler.ignore_errors();
  osmium::io::Reader reader{input_file};

  osmium::apply(reader, location_handler, data_handler,
                mp_manager.handler(
                    [&data_handler](const osmium::memory::Buffer &area_buffer) {
                      osmium::apply(area_buffer, data_handler);
                    }));

  reader.close();
  writer.close();
}
