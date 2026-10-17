find_package(Threads REQUIRED)
include_directories(${CMAKE_SOURCE_DIR}/src/common ${CMAKE_SOURCE_DIR}/3rdParty/spdlog/include)

set(SRC
    componentmodel.h
    propertyfields.h
    candbhandler.cpp
    candbpainter.cpp
    sortmodel.cpp
)

add_library(cds-common STATIC ${SRC})
target_include_directories(cds-common INTERFACE ${CMAKE_SOURCE_DIR}/src/common ${CMAKE_SOURCE_DIR}/3rdParty/spdlog/include)
target_link_libraries(cds-common ${CMAKE_THREAD_LIBS_INIT} Qt6::SerialBus nodes CANdb Qt6::Svg)

if(WITH_TESTS)
    add_executable(common_test tests/common_test.cpp)
    target_link_libraries(common_test Qt6::Test cds-common fakeit projectconfig)
    add_test(NAME common_test COMMAND common_test)
endif()

