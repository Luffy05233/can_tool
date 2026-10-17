cmake_minimum_required(VERSION 3.22)

project(CANdevStudio CXX)

set(VERSION_MAJOR 1)
set(VERSION_MINOR 2)
set(VERSION_PATCH 2)

set(CMAKE_INCLUDE_CURRENT_DIR ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTORCC ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_EXTENSIONS OFF)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_SOURCE_DIR}/cmake/Modules)

option(WITH_COVERAGE "Build with coverage" OFF)
option(WITH_TESTS "Build with test" ON)
option(WITH_TOOLS "Build tools directory" OFF)
option(DEV_BUILD "Development build will include GIT hash and branch to versioning" ON)
option(STANDALONE "Builds self containing package including Qt libs" OFF)

if(NOT CMAKE_INSTALL_LIBDIR)
    set(CMAKE_INSTALL_LIBDIR lib)
endif()
message(STATUS "CMAKE_INSTALL_LIBDIR: '${CMAKE_INSTALL_LIBDIR}'")

if(UNIX)
    if(STANDALONE)
        set(INSTALL_DEST_LIB CANdevStudio)
        set(INSTALL_DEST_BIN CANdevStudio)
        set(INSTALL_DEST_PLUG CANdevStudio/canbus)
    else()
        set(INSTALL_DEST_LIB ${CMAKE_INSTALL_LIBDIR}/CANdevStudio)
        set(INSTALL_DEST_BIN bin)
        set(INSTALL_DEST_PLUG ${CMAKE_INSTALL_LIBDIR}/qt6/plugins/canbus)
    endif()
else()
    set(GUI_TYPE WIN32)
    set(INSTALL_DEST_LIB CANdevStudio)
    set(INSTALL_DEST_BIN CANdevStudio)
endif()

find_package(Qt6 6.2 REQUIRED COMPONENTS
    Core SerialBus Widgets Test Svg Qml Quick QuickWidgets Network OpenGL)
message(STATUS "Qt Version found: ${Qt6_VERSION}")

# Older bundled non-Qt libraries still declare pre-3.5 CMake compatibility.
set(CMAKE_POLICY_VERSION_MINIMUM 3.5)

# Limit TYPESTRING to 128 (i.e. 2^7). 64 causes VS2015 internal error.
if(NOT MSVC)
    add_definitions(-Wall -Wextra -DUSE_TYPESTRING=7)
else()
    add_definitions( /bigobj /D USE_TYPESTRING=7 /Zc:__cplusplus /utf-8)
endif()

include(CompilerVersion)

if(WITH_COVERAGE)
    include(CodeCoverage)
    set(CMAKE_CXX_FLAGS ${CMAKE_CXX_FLAGS_COVERAGE})
    set(CMAKE_EXE_LINKER_FLAGS ${CMAKE_EXE_LINKER_FLAGS_COVERAGE})
    setup_target_for_coverage(NAME coverage EXECUTABLE ctest DEPENDENCIES candevice_test)
endif()

if(UNIX)
    set(CMAKE_CXX_FLAGS_RELEASE "-O3")
endif()

set(SPDLOG_BUILD_TESTING OFF CACHE BOOL "")
set(BUILD_EXAMPLES OFF CACHE BOOL "")
set(CANDB__WITH_TESTS OFF CACHE BOOL "")

# Version handling
if(EXISTS "${CMAKE_SOURCE_DIR}/.git" AND DEV_BUILD)
  execute_process(
    COMMAND git rev-parse --abbrev-ref HEAD
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_BRANCH
    OUTPUT_STRIP_TRAILING_WHITESPACE
  )

  execute_process(
    COMMAND git log -1 --format=%h
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_COMMIT_HASH
    OUTPUT_STRIP_TRAILING_WHITESPACE
  )
else()
  set(GIT_BRANCH "")
  set(GIT_COMMIT_HASH "")
endif()

message(STATUS "Git current branch: ${GIT_BRANCH}")
message(STATUS "Git commit hash: ${GIT_COMMIT_HASH}")

message(STATUS "Generating version.h")

configure_file(
  ${CMAKE_SOURCE_DIR}/src/common/version.h.in
  ${CMAKE_BINARY_DIR}/generated/version.h
)
# end of version Handling

if(WITH_TESTS OR WITH_COVERAGE)
    enable_testing()
endif()

add_subdirectory(3rdParty)
add_subdirectory(src/common)
add_subdirectory(src/components)
add_subdirectory(src/gui)

if(WITH_TOOLS)
    find_package(Boost COMPONENTS system filesystem REQUIRED)
    add_subdirectory(tools)
endif()

if(STANDALONE)
    if(Qt6_VERSION VERSION_LESS 6.7)
        message(FATAL_ERROR "Standalone deployment requires Qt 6.7 or newer.")
    endif()
    qt_generate_deploy_app_script(
        TARGET CANdevStudio
        OUTPUT_SCRIPT deploy_script
        NO_UNSUPPORTED_PLATFORM_ERROR
    )
    install(SCRIPT ${deploy_script})
endif()

include("packaging.cmake")

if(WITH_TESTS)
    add_executable(qt6_runtime_test tests/qt6_runtime_test.cpp
        src/components/qmlexecutor/canbusmodel.hpp)
    target_include_directories(qt6_runtime_test PRIVATE src/components/qmlexecutor)
    target_link_libraries(qt6_runtime_test PRIVATE
        Qt6::Widgets Qt6::QuickWidgets Qt6::Qml Qt6::SerialBus Qt6::Test)
    target_compile_definitions(qt6_runtime_test PRIVATE
        CDS_QML_EXAMPLES="${CMAKE_CURRENT_SOURCE_DIR}/src/components/qmlexecutor/examples")
    if(TARGET qtCannelloniCanBusPlugin)
        add_dependencies(qt6_runtime_test qtCannelloniCanBusPlugin)
        target_compile_definitions(qt6_runtime_test PRIVATE
            CDS_CAN_PLUGIN_PATH="${CMAKE_BINARY_DIR}/src/gui")
    endif()
    add_test(NAME qt6_runtime_test COMMAND qt6_runtime_test)
    set_tests_properties(qt6_runtime_test PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;QT_QUICK_BACKEND=software")
endif()
