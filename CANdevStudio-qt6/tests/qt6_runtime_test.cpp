#include <QCanBus>
#include <QCanBusDevice>
#include <QPlainTextEdit>
#include <QQmlContext>
#include <QQuickWidget>
#include <QSignalSpy>
#include <QtTest>
#include <memory>
#include "canbusmodel.hpp"

class Qt6RuntimeTest : public QObject
{
    Q_OBJECT
private slots:
    void cannelloniPlugin()
    {
#ifdef CDS_CAN_PLUGIN_PATH
        QCoreApplication::addLibraryPath(QStringLiteral(CDS_CAN_PLUGIN_PATH));
        auto* bus = QCanBus::instance();
        QVERIFY(bus->plugins().contains("cannelloni"));
        QString error;
        QVERIFY(bus->availableDevices("cannelloni", &error).isEmpty());
        QVERIFY2(error.isEmpty(), qPrintable(error));
        std::unique_ptr<QCanBusDevice> device(
            bus->createDevice("cannelloni", "12000,127.0.0.1,12001", &error));
        QVERIFY2(device != nullptr, qPrintable(error));
        // Construct only: never connect or send traffic to a real interface.
        QCOMPARE(device->state(), QCanBusDevice::UnconnectedState);
        QVERIFY(!bus->createDevice("cannelloni", "invalid", &error));
        QVERIFY(!error.isEmpty());
#endif
    }

    void qmlExamples_data()
    {
        QTest::addColumn<QString>("file");
        QTest::newRow("timer") << "simple_timer.qml";
        QTest::newRow("forwarder") << "simple_forwarder.qml";
        QTest::newRow("controls") << "sample.qml";
    }

    void qmlExamples()
    {
        QFETCH(QString, file);
        CANBusModel model;
        QPlainTextEdit log;
        QQuickWidget view;
        view.rootContext()->setContextProperty("CANBusModel", &model);
        view.rootContext()->setContextProperty("LogWindow", &log);
        view.setSource(QUrl::fromLocalFile(QStringLiteral(CDS_QML_EXAMPLES) + '/' + file));
        QTRY_COMPARE(view.status(), QQuickWidget::Ready);
        if (file == "simple_timer.qml") {
            QSignalSpy frames(&model, &CANBusModel::sendFrame);
            emit model.simulationStarted();
            QTRY_VERIFY(frames.count() >= 2);
            emit model.simulationStopped();
            for (const auto& args : frames) {
                const auto id = args[0].toUInt();
                const auto payload = args[1].toByteArray();
                QVERIFY(id == 0x112233 || id == 0x7ff);
                QCOMPARE(payload.size(), id == 0x112233 ? 4 : 8);
            }
        }
    }
};

QTEST_MAIN(Qt6RuntimeTest)
#include "qt6_runtime_test.moc"
