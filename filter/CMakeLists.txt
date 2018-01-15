cmake_minimum_required(VERSION 2.8)
set(NAME filter_planet_by_cats)
project(${NAME} C CXX)
set(CMAKE_CXX_STANDARD 11)
message(STATUS "Configuring ${NAME}")
list(APPEND CMAKE_MODULE_PATH "${CMAKE_SOURCE_DIR}")
find_package(Osmium REQUIRED COMPONENTS io)
include_directories(SYSTEM ${OSMIUM_INCLUDE_DIRS})
add_executable(
  ${NAME}
  ${NAME}.cpp
  RTree.h
  xml_centers_output.hpp
)
target_link_libraries(${NAME} ${OSMIUM_IO_LIBRARIES})
