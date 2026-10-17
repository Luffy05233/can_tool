cmake_minimum_required(VERSION 3.16)
project(qtCannelloniCanBusPlugin CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall")

find_package(Qt6Core REQUIRED)
find_package(Qt6SerialBus REQUIRED)
find_package(Qt6Network REQUIRED)

include_directories(${Qt6Core_INCLUDE_DIRS} ${Qt6SerialBus_INCLUDE_DIRS}
    ${Qt6Network_INCLUDE_DIRS} ${CMAKE_BINARY_DIR})

add_library(${PROJECT_NAME} SHARED
  QtCannelloniCanBusPlugin.cpp
  CannelloniCanBackend.cpp
  cannelloni/parser.cpp
  )

target_link_libraries(${PROJECT_NAME} Qt6::Core Qt6::SerialBus Qt6::Network)
