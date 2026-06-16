import QtQuick
import QtQuick.Controls.Basic
import Pju

Button {
    id: control

    // primary | secondary | danger | purple | ghost
    property string variant: "primary"

    font.pixelSize: Theme.fontSize
    font.bold: true
    topPadding: 10
    bottomPadding: 10
    leftPadding: 22
    rightPadding: 22

    readonly property bool _filled: variant === "primary" || variant === "danger" || variant === "purple"

    readonly property color _bg: {
        if (!control.enabled) {
            if (variant === "primary") return Theme.accentDisabled
            if (variant === "purple") return Theme.purpleDisabled
            if (variant === "danger") return Theme.danger
            return Theme.surfaceMuted
        }
        if (variant === "primary")
            return control.down ? Theme.accentPressed : (control.hovered ? Theme.accentHover : Theme.accent)
        if (variant === "purple")
            return control.down ? Theme.purplePressed : (control.hovered ? Theme.purpleHover : Theme.purple)
        if (variant === "danger")
            return control.down ? Theme.dangerPressed : (control.hovered ? Theme.dangerHover : Theme.danger)
        if (variant === "ghost")
            return control.hovered ? Theme.surfaceMuted : "transparent"
        return control.down || control.hovered ? Theme.surfaceMuted : Theme.surface
    }

    readonly property color _fg: {
        if (_filled) return Theme.textOnAccent
        return control.enabled ? Theme.textBody : Theme.textSubtle
    }

    readonly property bool _outlined: variant === "secondary" || variant === "ghost"

    HoverHandler {
        enabled: control.enabled
        cursorShape: Qt.PointingHandCursor
    }

    contentItem: Text {
        text: control.text
        font: control.font
        color: control._fg
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 8
        color: control._bg
        border.width: control._outlined ? 1 : 0
        border.color: control.hovered ? Theme.borderStrong : Theme.border
    }
}
