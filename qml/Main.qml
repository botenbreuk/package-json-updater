import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Pju
import "controls"
import "components"
import "screens"

ApplicationWindow {
    id: root

    visible: true
    width: 1280
    height: 720
    minimumWidth: 1000
    minimumHeight: 600
    title: qsTr("Package.json Updater")
    color: Theme.window

    property bool versionsReady: false
    property bool settingsOpen: false
    property bool hardRefresh: false
    property bool installVisible: false
    property string pendingUpdateMode: ""
    property string pendingAction: ""
    readonly property string view: settingsOpen ? "settings"
                                                 : (Project.hasFile ? "table" : "start")

    Component.onCompleted: Theme.dark = Qt.binding(() => App.dark)

    Connections {
        target: App
        function onVersionsChanged() {
            root.versionsReady = true
            Git.setNodeVersion(App.nodeVersion)
        }
        function onFlash(message) { flashMsg.show(message) }
    }

    Connections {
        target: Git
        function onReloadRequested() { Project.reopen() }
        function onPullFailed(message) {
            root.pendingAction = ""
            modal.show({ "title": qsTr("git pull failed"), "message": message })
        }
    }

    Connections {
        target: Project
        function onOpenError(title, body) {
            root.pendingAction = ""
            modal.show({ "title": title, "message": body })
        }
        function onInfoMessage(title, body) {
            root.pendingAction = ""
            modal.show({ "title": title, "message": body })
        }
        function onConfirmUpdateAll(count, label, mode) {
            root.pendingUpdateMode = mode
            root.pendingAction = "updateAll"
            modal.show({
                "title": qsTr("Confirm Update All"),
                "message": qsTr("Update %1 package(s) using mode: %2?\nThis will overwrite your package.json.").arg(count).arg(label),
                "showCancel": true,
                "confirmText": qsTr("Update")
            })
        }
        function onHasFileChanged() { Git.setProject(Project.projectDir) }
    }

    Connections {
        target: Install
        function onSucceeded() { Project.clearPending() }
    }

    Shortcut {
        sequences: [StandardKey.Refresh]
        enabled: Project.hasFile
        onActivated: Project.startRefresh(root.hardRefresh)
    }

    header: ToolBar {
        implicitHeight: 46

        background: Rectangle {
            color: Theme.toolbarBg
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.border
            }
        }

        contentItem: Item {

        RowLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 2

            AppToolButton {
                text: qsTr("←  Back")
                visible: root.settingsOpen
                onClicked: root.settingsOpen = false
            }

            Text {
                visible: root.settingsOpen
                text: qsTr("Settings")
                color: Theme.textHeading
                font.pixelSize: 15
                font.bold: true
                leftPadding: 4
            }

            AppToolButton {
                text: qsTr("📂  Open package.json")
                visible: !root.settingsOpen && !Project.hasFile
                onClicked: fileDialog.open()
            }

            AppToolButton {
                text: qsTr("📁  Open Folder")
                visible: !root.settingsOpen && !Project.hasFile
                onClicked: folderDialog.open()
            }

            Row {
                visible: !root.settingsOpen && Project.hasFile
                spacing: 0

                AppToolButton {
                    text: root.hardRefresh ? qsTr("↺  Hard Refresh") : qsTr("↺  Refresh")
                    enabled: !Project.isFetching
                    onClicked: Project.startRefresh(root.hardRefresh)
                }
                AppToolButton {
                    text: "▾"
                    onClicked: refreshMenu.popup()
                }
            }

            AppToolButton {
                text: qsTr("⚙  Settings")
                visible: !root.settingsOpen
                onClicked: {
                    settingsPage.syncFromSettings()
                    root.settingsOpen = true
                }
            }

            Item { Layout.fillWidth: true }

            Row {
                Layout.alignment: Qt.AlignVCenter
                visible: !root.settingsOpen && Project.hasFile && Git.hasRepo
                spacing: 8

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    height: 24
                    width: branchText.implicitWidth + 16
                    radius: 5
                    readonly property bool warn: Git.behind > 0 && !Git.fetching
                    color: Git.fetching ? Theme.surfaceMuted
                         : (warn ? (Theme.dark ? "#451a03" : "#fef9c3")
                                 : (Theme.dark ? "#14532d" : "#dcfce7"))
                    border.width: 1
                    border.color: Git.fetching ? Theme.border
                                : (warn ? (Theme.dark ? "#b45309" : "#fcd34d")
                                        : (Theme.dark ? "#166534" : "#86efac"))

                    Text {
                        id: branchText
                        anchors.centerIn: parent
                        text: "⎇ " + Git.branch + (Git.behind > 0 ? "  ↓" + Git.behind : "")
                        font.pixelSize: 13
                        font.bold: true
                        color: Git.fetching ? Theme.textMuted
                             : (parent.warn ? (Theme.dark ? "#fcd34d" : "#92400e")
                                            : (Theme.dark ? "#4ade80" : "#15803d"))
                    }
                }

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: Git.behind > 0 && !Git.fetching
                    height: 24
                    width: pullText.implicitWidth + 20
                    radius: 5
                    opacity: Git.pulling ? 0.6 : 1
                    color: pullMouse.containsMouse ? (Theme.dark ? "#1d4ed8" : "#dbeafe")
                                                   : (Theme.dark ? "#1e3a5f" : "#eff6ff")
                    border.width: 1
                    border.color: Theme.dark ? "#2563eb" : "#93c5fd"

                    Text {
                        id: pullText
                        anchors.centerIn: parent
                        text: Git.pulling ? qsTr("Pulling…") : qsTr("↓ Pull")
                        font.pixelSize: 13
                        font.bold: true
                        color: Theme.dark ? "#93c5fd" : "#2563eb"
                    }

                    MouseArea {
                        id: pullMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: !Git.pulling
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Git.pull()
                    }
                }
            }

            AppToolButton {
                text: qsTr("✕  Close")
                visible: !root.settingsOpen && Project.hasFile
                accentColor: Theme.danger
                onClicked: Project.closeFile()
            }
        }
        }
    }

    AppMenu {
        id: refreshMenu
        AppMenuItem { text: qsTr("↺  Refresh"); onTriggered: root.hardRefresh = false }
        AppMenuItem { text: qsTr("↺  Hard Refresh"); onTriggered: root.hardRefresh = true }
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: root.view === "start" ? 0 : (root.view === "table" ? 1 : 2)

        StartScreen {
            onOpenFileRequested: fileDialog.open()
            onOpenFolderRequested: folderDialog.open()
        }

        ProjectView {
            onNpmInstallRequested: {
                Install.start(Project.projectDir)
                root.installVisible = true
            }
        }

        SettingsPage {
            id: settingsPage
            onClearCacheRequested: {
                root.pendingAction = "clearCache"
                modal.show({
                    "title": qsTr("Clear cache?"),
                    "message": qsTr("All locally stored npm version data will be deleted. The next time you open a project every package will be re-fetched from the npm registry."),
                    "showCancel": true,
                    "confirmText": qsTr("Clear Cache"),
                    "danger": true
                })
            }
        }
    }

    Loader {
        anchors.fill: parent
        active: root.installVisible
        sourceComponent: Component {
            NpmInstallOverlay {
                onClosed: root.installVisible = false
            }
        }
    }

    FlashMessage { id: flashMsg }

    footer: Rectangle {
        implicitHeight: 30
        color: Theme.statusBg

        Rectangle {
            anchors.top: parent.top
            width: parent.width
            height: 1
            color: Theme.border
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 10

            Text {
                Layout.fillWidth: true
                text: Project.statusMessage !== "" ? Project.statusMessage
                    : (Project.hasFile ? "" : qsTr("No file loaded. Open a package.json to begin."))
                font.pixelSize: 14
                color: Theme.statusText
                elide: Text.ElideRight
            }

            Text {
                visible: Project.hasFile
                Layout.maximumWidth: 360
                text: Project.filePath
                font.pixelSize: 13
                color: Theme.textSubtle
                elide: Text.ElideLeft
            }

            Text {
                visible: Git.nvmrcText !== ""
                text: Git.nvmrcText
                font.pixelSize: 13
                font.bold: true
                color: Git.nvmrcWarn ? Theme.warn : Theme.textMuted
            }

            Text {
                visible: Git.nvmrcText !== ""
                text: "·"
                font.pixelSize: 13
                color: Theme.textSubtle
            }

            Text {
                text: !root.versionsReady ? qsTr("node …")
                    : (App.nodeVersion ? qsTr("node %1").arg(App.nodeVersion) : qsTr("node —"))
                font.pixelSize: 13
                color: Theme.statusText
            }

            Text {
                text: "·"
                font.pixelSize: 13
                color: Theme.textSubtle
            }

            Text {
                text: !root.versionsReady ? qsTr("npm …")
                    : (App.npmVersion ? qsTr("npm %1").arg(App.npmVersion) : qsTr("npm —"))
                font.pixelSize: 13
                color: Theme.statusText
            }
        }
    }

    FileDialog {
        id: fileDialog
        title: qsTr("Open package.json")
        currentFolder: Project.initialFileDir
        nameFilters: [qsTr("package.json (package.json)"), qsTr("All files (*)")]
        onAccepted: Project.openFileUrl(selectedFile)
    }

    FolderDialog {
        id: folderDialog
        title: qsTr("Open Folder containing package.json")
        currentFolder: Project.initialFolderDir
        onAccepted: Project.openFolderUrl(selectedFolder)
    }

    ModalDialog {
        id: modal
        onAccepted: {
            if (root.pendingAction === "updateAll")
                Project.applyUpdateAll(root.pendingUpdateMode)
            else if (root.pendingAction === "clearCache")
                App.clearCache()
            root.pendingAction = ""
        }
        onRejected: root.pendingAction = ""
    }
}
