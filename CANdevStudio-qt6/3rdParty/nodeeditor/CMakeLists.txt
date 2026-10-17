cmake_minimum_required(VERSION 3.16)

project(NodeEditor CXX)

set(CMAKE_DISABLE_IN_SOURCE_BUILD ON)
set(CMAKE_DISABLE_SOURCE_CHANGES  ON)

# Find includes in corresponding build directories
set(CMAKE_INCLUDE_CURRENT_DIR ON)

set(CMAKE_EXPORT_COMPILE_COMMANDS "ON")

# Instruct CMake to run moc automatically when needed.
set(CMAKE_AUTOMOC ON)

option(BUILD_EXAMPLES "Build Examples" ON)


# Find the QtWidgets library
find_package(Qt6 REQUIRED COMPONENTS
             Core
             Widgets
             Gui
             OpenGL)


if(MSVC)
  add_definitions(/Wall /EHsc)
else()
  add_definitions(-Wall -Wextra)
endif(MSVC)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

#############################################################

file(GLOB_RECURSE LIB_CPPS  ./src/*.cpp )

qt6_add_resources(RESOURCES ./resources/resources.qrc)

# Tell CMake to create the helloworld executable
add_library(nodes STATIC ${LIB_CPPS} ${RESOURCES})

target_include_directories(nodes INTERFACE "include")

target_compile_definitions(nodes PUBLIC "-DNODE_EDITOR_STATIC")
target_compile_definitions(nodes PRIVATE "-DNODE_EDITOR_EXPORTS")

target_link_libraries(nodes
                      Qt6::Core
                      Qt6::Widgets
                      Qt6::Gui
                      Qt6::OpenGL)

if(BUILD_EXAMPLES)
  add_subdirectory(examples)
endif()
