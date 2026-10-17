set(COMPONENT_NAME qmlexecutor)

set(SRC
    gui/qmlexecutor.ui
    gui/qmlexecutorguiimpl.h
    gui/qmlexecutorguiint.h
    qmlexecutor.cpp
    qmlexecutor_p.cpp
    qmlexecutormodel.cpp
    canbusmodel.hpp
)

set(QT_QML_LIBS Qt6::Quick  Qt6::Widgets Qt6::Qml Qt6::QuickWidgets)

add_library(${COMPONENT_NAME} ${SRC})
target_link_libraries(${COMPONENT_NAME} cds-common ${QT_QML_LIBS})
target_include_directories(${COMPONENT_NAME} INTERFACE ${Qt6Widgets_INCLUDE_DIRS})
target_include_directories(${COMPONENT_NAME} INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})

if(WITH_TESTS)

    add_executable(${COMPONENT_NAME}_test tests/${COMPONENT_NAME}_test.cpp tests/guimock.h)
    target_link_libraries(${COMPONENT_NAME}_test ${COMPONENT_NAME} Qt6::Test fakeit ${QT_QML_LIBS})
    add_test(NAME ${COMPONENT_NAME}_test COMMAND ${COMPONENT_NAME}_test)

    add_executable(${COMPONENT_NAME}model_test tests/${COMPONENT_NAME}model_test.cpp)
    target_link_libraries(${COMPONENT_NAME}model_test ${COMPONENT_NAME} Qt6::Test fakeit ${QT_QML_LIBS})
    add_test(NAME ${COMPONENT_NAME}model_test COMMAND ${COMPONENT_NAME}model_test)
endif()
