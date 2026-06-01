# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Package.json Updater."""
import re
import sys
from pathlib import Path

block_cipher = None

PROJECT_ROOT = Path(SPECPATH).parent
RELEASE_DIR = PROJECT_ROOT / "release"

VERSION = re.search(
    r'VERSION\s*=\s*"([^"]+)"',
    (PROJECT_ROOT / "_version.py").read_text(),
).group(1)

if sys.platform == "darwin":
    icon_file = str(RELEASE_DIR / "icons" / "icon.icns")
elif sys.platform == "win32":
    icon_file = str(RELEASE_DIR / "icons" / "icon.ico")
else:
    icon_file = str(RELEASE_DIR / "icons" / "icon.png")

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "assets"), "assets"),
    ],
    hiddenimports=[
        "_version",
        "core",
        "core.npm_registry",
        "core.npm_cache",
        "core.package_json",
        "core.semver_utils",
        "core.node_env",
        "models",
        "models.dependency",
        "models.settings",
        "ui",
        "ui.main_window",
        "ui.start_screen",
        "ui.dependency_table",
        "ui.version_cell_widget",
        "ui.version_delegate",
        "ui.settings_page",
        "ui.settings_dialog",
        "ui.npm_install_dialog",
        "workers",
        "workers.fetch_worker",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtSvg",
        "requests",
        "packaging",
        "packaging.version",
        "packaging.specifiers",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="PackageJsonUpdater",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_file,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="PackageJsonUpdater",
    )

    app = BUNDLE(
        coll,
        name="PackageJsonUpdater.app",
        icon=icon_file,
        bundle_identifier="nl.42.package-json-updater",
        info_plist={
            "CFBundleDisplayName": "Package.json Updater",
            "CFBundleShortVersionString": VERSION,
            "CFBundleIconFile": "icon.icns",
            "NSHighResolutionCapable": True,
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="PackageJsonUpdater",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_file,
    )
