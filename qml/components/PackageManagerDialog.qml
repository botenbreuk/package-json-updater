import QtQuick
import QtQuick.Layouts
import App
import "../controls"

// Modal picker for choosing the project's package manager.  Styled after
// ModalDialog; opened via Pm.showPicker and applies through Pm.choose.
Item {
    id: dlg
    anchors.fill: parent
    visible: active
    z: 2500

    property bool active: false
    property string selectedId: "npm"
    property var lockmap: ({})
    property bool remember: true

    readonly property var managers: [
        { id: "npm",  name: "npm" },
        { id: "yarn", name: "Yarn" },
        { id: "pnpm", name: "pnpm" },
        { id: "bun",  name: "Bun" }
    ]

    readonly property int candidateCount: Object.keys(lockmap).length

    function nameFor(id) {
        for (var i = 0; i < managers.length; i++)
            if (managers[i].id === id) return managers[i].name
        return id
    }

    function open(currentId) {
        selectedId = (currentId && currentId !== "") ? currentId : "npm"
        lockmap = Pm.detectedLockfiles()
        remember = true
        active = true
    }

    Rectangle {
        anchors.fill: parent
        color: "#000000"
        opacity: 0.55
        MouseArea { anchors.fill: parent }      // swallow clicks behind the card
    }

    Rectangle {
        anchors.centerIn: parent
        width: 460
        implicitHeight: col.implicitHeight + 48
        radius: 12
        color: Theme.surface
        border.width: 1
        border.color: Theme.border

        ColumnLayout {
            id: col
            anchors.fill: parent
            anchors.margins: 24
            spacing: 12

            Text {
                Layout.fillWidth: true
                text: qsTr("Which package manager?")
                font.pixelSize: 18
                font.bold: true
                color: Theme.textHeading
                wrapMode: Text.WordWrap
            }

            Text {
                Layout.fillWidth: true
                text: dlg.candidateCount > 1
                    ? qsTr("More than one lockfile was found. Pick the manager this project uses.")
                    : qsTr("Choose the package manager to use for this project.")
                font.pixelSize: Theme.fontSize
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }

            Repeater {
                model: dlg.managers
                delegate: Rectangle {
                    id: optRow
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 46
                    radius: 10
                    readonly property bool sel: dlg.selectedId === modelData.id
                    readonly property string lock:
                        dlg.lockmap[modelData.id] !== undefined ? dlg.lockmap[modelData.id] : ""
                    color: sel ? Theme.accentSoftBg : Theme.surface
                    border.width: sel ? 2 : 1
                    border.color: sel ? Theme.accent : Theme.border

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 11

                        Rectangle {
                            width: 18; height: 18; radius: 9
                            color: "transparent"
                            border.width: 2
                            border.color: optRow.sel ? Theme.accent : Theme.borderStrong
                            Rectangle {
                                anchors.centerIn: parent
                                width: 9; height: 9; radius: 5
                                visible: optRow.sel
                                color: Theme.accent
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: optRow.modelData.name
                            font.pixelSize: Theme.fontSize
                            font.bold: true
                            color: Theme.textBody
                        }

                        Text {
                            text: optRow.lock !== "" ? optRow.lock : "—"
                            font.pixelSize: 12
                            font.family: Theme.monoFamily
                            color: optRow.sel ? Theme.accent : Theme.textSubtle
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: dlg.selectedId = optRow.modelData.id
                    }
                }
            }

            AppCheckBox {
                Layout.topMargin: 2
                checked: dlg.remember
                label: qsTr("Remember for this folder")
                onToggled: dlg.remember = !dlg.remember
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 8

                Item { Layout.fillWidth: true }

                AppButton {
                    variant: "ghost"
                    text: qsTr("Cancel")
                    Layout.preferredHeight: 40
                    onClicked: dlg.active = false
                }

                AppButton {
                    variant: "primary"
                    text: qsTr("Use %1").arg(dlg.nameFor(dlg.selectedId))
                    Layout.preferredHeight: 40
                    onClicked: {
                        Pm.choose(dlg.selectedId, dlg.remember)
                        dlg.active = false
                    }
                }
            }
        }
    }
}
