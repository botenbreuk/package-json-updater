import QtQuick

// Reusable button built on primitives — avoids Qt Quick Controls style conflicts.
// isDark is passed in from the parent component.
Item {
    id: root

    // "primary" | "secondary" | "ghost"
    property string variant: "primary"
    // "small" | "medium" | "large"
    property string size: "medium"
    property bool   isDark: false
    property bool   enabled: true
    property string text: ""

    signal clicked()

    readonly property int _hPad: size === "small" ? 10 : size === "large" ? 22 : 14
    readonly property int _vPad: size === "small" ? 5  : size === "large" ? 10 : 7
    readonly property int _fontSize: size === "small" ? 13 : size === "large" ? 15 : 13

    implicitWidth:  label.implicitWidth + _hPad * 2
    implicitHeight: label.implicitHeight + _vPad * 2

    // ── colors matched to the original widget stylesheet ──────────────────────
    readonly property color _bg: {
        if (!enabled) return isDark ? "#1e293b" : "#f1f5f9"
        if (variant === "primary")   return "#3b82f6"
        if (variant === "secondary") return isDark ? "#1e293b" : "#ffffff"
        return "transparent"
    }
    readonly property color _bgHover: {
        if (variant === "primary")   return "#2563eb"
        if (variant === "secondary") return isDark ? "#334155" : "#f1f5f9"
        return isDark ? "#FFFFFF10" : "#00000008"
    }
    readonly property color _bgPressed: {
        if (variant === "primary")   return "#1d4ed8"
        if (variant === "secondary") return isDark ? "#475569" : "#e2e8f0"
        return isDark ? "#FFFFFF18" : "#00000012"
    }
    readonly property color _fg: {
        if (!enabled)                return isDark ? "#475569" : "#94a3b8"
        if (variant === "primary")   return "#ffffff"
        if (variant === "secondary") return isDark ? "#cbd5e1" : "#334155"
        return isDark ? "#94a3b8"  : "#94a3b8"
    }
    readonly property color _border: {
        if (variant === "secondary")
            return ma.containsMouse
                   ? (isDark ? "#475569" : "#94a3b8")
                   : (isDark ? "#334155" : "#e2e8f0")
        return "transparent"
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color:  ma.pressed && root.enabled ? root._bgPressed
              : ma.containsMouse && root.enabled ? root._bgHover
              : root._bg
        border.color: root._border
        border.width: root.variant === "secondary" ? 1.5 : 0
        Behavior on color        { ColorAnimation { duration: 80 } }
        Behavior on border.color { ColorAnimation { duration: 80 } }
    }

    Text {
        id: label
        anchors.centerIn: parent
        text:           root.text
        font.pixelSize: root._fontSize
        font.weight:    Font.DemiBold
        color:          root._fg
        Behavior on color { ColorAnimation { duration: 80 } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape:  root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        enabled:      root.enabled
        onClicked:    root.clicked()
    }
}
