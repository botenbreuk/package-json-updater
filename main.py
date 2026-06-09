"""
Package.json Updater — desktop application entry point.

Run with:
    python main.py
"""
import signal
import sys
import os

# Make the project root importable from any working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QStyleFactory
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow
from _version import VERSION

_ROOT = os.path.dirname(os.path.abspath(__file__))

def _asset(name: str) -> str:
    return os.path.join(_ROOT, "assets", name)


def main() -> None:
    # Enable high-DPI support
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    app = QApplication(sys.argv)

    # Force Qt's own Fusion renderer so that ALL appearance (including floating
    # pop-ups like ComboBox drop-downs) is controlled by our stylesheet and
    # never overridden by the macOS system light/dark theme.
    app.setStyle(QStyleFactory.create("Fusion"))

    app.setApplicationName("Package.json Updater")
    app.setOrganizationName("42nl")
    app.setApplicationVersion(VERSION)

    png_path = os.path.join(_ROOT, "release", "icons", "icon.png")
    pix = QPixmap(png_path)
    pix.setDevicePixelRatio(2.0)  # 1024px image → 512dp @2x
    icon = QIcon(pix)
    app.setWindowIcon(icon)   # dock / taskbar

    window = MainWindow()
    window.setWindowIcon(icon)  # title bar & Alt+Tab thumbnail
    window.show()

    # Allow passing a package.json path as a command-line argument
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.isfile(path):
            window._open_file(os.path.abspath(path))

    # Restore the OS default SIGINT handler so Ctrl+C terminates the process
    # cleanly.  Without this Qt's C++ event loop intercepts the signal at an
    # arbitrary point and calls abort(), producing the ugly traceback + crash.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
