import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

// Start screen — shown when no package.json is loaded.
// Requires context property: bridge (StartScreenBridge)
Item {
    id: root

    SystemPalette { id: sysPalette }
    readonly property bool _dark: sysPalette.windowText.hslLightness > 0.5

    // ── background ────────────────────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: _dark ? "#0f172a" : "#f8fafc"
    }

    // ── fixed section: hero + buttons + "Recent" header ───────────────────────
    Item {
        id: fixedSection
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width - 48, 520)
        height: fixedCol.implicitHeight

        y: bridge.recentFiles.length === 0
           ? Math.max(48, (root.height - height) / 2)
           : Math.max(48, (root.height - height - recentSection.height - 16) / 2)

        ColumnLayout {
            id: fixedCol
            width: parent.width
            spacing: 0

            Text {
                text: "📦"
                font.pixelSize: 52
                Layout.alignment: Qt.AlignHCenter
            }

            Item { Layout.preferredHeight: 14 }

            Text {
                text: "Package.json Updater"
                font.pixelSize: 24
                font.weight: Font.Bold
                color: _dark ? "#f1f5f9" : "#0f172a"
                Layout.alignment: Qt.AlignHCenter
            }

            Item { Layout.preferredHeight: 6 }

            Text {
                text: "Check and update npm dependencies"
                font.pixelSize: 15
                color: "#64748b"           // same in light and dark per original
                Layout.alignment: Qt.AlignHCenter
            }

            Item { Layout.preferredHeight: 28 }

            RowLayout {
                spacing: 10
                Layout.alignment: Qt.AlignHCenter

                AppButton {
                    text: "📁  Open Folder"
                    variant: "secondary"
                    size: "large"
                    isDark: _dark
                    onClicked: bridge.openFolder()
                }
                AppButton {
                    text: "📄  Open package.json"
                    variant: "primary"
                    size: "large"
                    isDark: _dark
                    onClicked: bridge.openFile()
                }
            }

            Item { Layout.preferredHeight: 32; visible: bridge.recentFiles.length > 0 }

            // "Recent" header — never scrolls
            RowLayout {
                Layout.fillWidth: true
                visible: bridge.recentFiles.length > 0
                spacing: 0

                Text {
                    text: "RECENT"
                    font.pixelSize: 13
                    font.weight: Font.Bold
                    color: _dark ? "#475569" : "#94a3b8"
                    leftPadding: 2
                    Layout.fillWidth: true
                }

                // "Clear all" — turns red on hover, matching original recentClearBtn
                Item {
                    implicitWidth:  clearLbl.implicitWidth + 8
                    implicitHeight: clearLbl.implicitHeight + 4

                    Text {
                        id: clearLbl
                        anchors.centerIn: parent
                        text: "Clear all"
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        color: clearMa.containsPress ? "#dc2626"
                             : clearMa.containsMouse ? "#ef4444"
                             : (_dark ? "#475569" : "#94a3b8")
                        Behavior on color { ColorAnimation { duration: 80 } }
                    }
                    MouseArea {
                        id: clearMa; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.clearRecents()
                    }
                }
            }
        }
    }

    // ── scrollable recent list ────────────────────────────────────────────────
    Item {
        id: recentSection
        visible: bridge.recentFiles.length > 0
        anchors {
            top: fixedSection.bottom; topMargin: 10
            bottom: parent.bottom;    bottomMargin: 48
            horizontalCenter: parent.horizontalCenter
        }
        width: fixedSection.width
        clip: true

        ListView {
            id: recentList
            anchors.fill: parent
            model: bridge.recentFiles
            spacing: 6
            clip: true

            ScrollBar.vertical: ScrollBar {
                policy: recentList.contentHeight > recentList.height
                        ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
            }

            delegate: Rectangle {
                id: row
                width: recentList.width
                height: 64
                radius: 10
                color: rowHover.containsMouse
                       ? (_dark ? "#1e3a5f" : "#eff6ff")
                       : (_dark ? "#1e293b" : "#f8fafc")
                border.color: rowHover.containsMouse
                              ? (_dark ? "#3b82f6" : "#bfdbfe")
                              : (_dark ? "#334155" : "#e2e8f0")
                border.width: 1
                Behavior on color        { ColorAnimation { duration: 80 } }
                Behavior on border.color { ColorAnimation { duration: 80 } }

                readonly property string _path: modelData.path || ""
                readonly property string _name: {
                    var parts = _path.replace(/\\/g, "/").split("/")
                    return parts.length >= 2
                           ? parts[parts.length - 2]
                           : parts[parts.length - 1] || "unknown"
                }
                readonly property string _age: {
                    var ts = modelData.last_checked
                    if (!ts) return "Never checked"
                    var s = (Date.now() - new Date(ts).getTime()) / 1000
                    if (s < 60)    return "Checked just now"
                    if (s < 3600)  return "Checked " + Math.floor(s / 60) + "m ago"
                    if (s < 86400) return "Checked " + Math.floor(s / 3600) + "h ago"
                    var d = Math.floor(s / 86400)
                    if (d === 1)   return "Checked yesterday"
                    if (d < 30)    return "Checked " + d + " days ago"
                    if (d < 365)   return "Checked " + Math.floor(d / 30) + "mo ago"
                    return "Checked " + Math.floor(d / 365) + "y ago"
                }

                MouseArea {
                    id: rowHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bridge.openFilePath(row._path)
                }

                RowLayout {
                    anchors {
                        left: parent.left; right: parent.right
                        verticalCenter: parent.verticalCenter
                    }
                    anchors.leftMargin: 14; anchors.rightMargin: 12
                    spacing: 0

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3

                        Text {
                            text: row._name
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                            color: _dark ? "#e2e8f0" : "#1e293b"
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Text {
                            text: row._path
                            font.pixelSize: 13
                            color: _dark ? "#475569" : "#94a3b8"
                            elide: Text.ElideLeft
                            Layout.fillWidth: true
                        }
                    }

                    Item { Layout.preferredWidth: 12 }

                    Text {
                        text: row._age
                        font.pixelSize: 13
                        color: _dark ? "#475569" : "#64748b"
                    }

                    Item { Layout.preferredWidth: 8 }

                    // Remove (×) — red hover matching original recentRemoveBtn
                    Rectangle {
                        width: 26; height: 26; radius: 4
                        color: removeMa.containsPress ? (_dark ? "#7f1d1d" : "#fecaca")
                             : removeMa.containsMouse ? (_dark ? "#450a0a" : "#fee2e2")
                             : "transparent"
                        Behavior on color { ColorAnimation { duration: 80 } }

                        Text {
                            anchors.centerIn: parent
                            text: "×"
                            font.pixelSize: 16
                            color: removeMa.containsMouse ? "#ef4444"
                                 : (_dark ? "#94a3b8" : "#64748b")
                            Behavior on color { ColorAnimation { duration: 80 } }
                        }
                        MouseArea {
                            id: removeMa; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: bridge.removeRecent(row._path)
                        }
                    }
                }
            }
        }
    }
}
