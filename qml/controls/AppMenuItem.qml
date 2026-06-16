import QtQuick
import QtQuick.Controls.Basic
import Pju

MenuItem {
    id: item
    implicitHeight: 32

    contentItem: Text {
        text: item.text
        color: Theme.textBody
        font.pixelSize: Theme.fontSize
        verticalAlignment: Text.AlignVCenter
        leftPadding: 8
    }

    background: Rectangle {
        radius: 6
        color: item.highlighted ? Theme.accentSoftBg : "transparent"
    }
}
