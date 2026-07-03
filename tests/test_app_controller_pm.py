"""
Phase 5 tests: the AppController API backing the Settings › Package Managers
panel — the global default and the per-folder override list/removal.

Storage is isolated to a temp config dir; a QCoreApplication is created so the
controller's Qt machinery works headlessly.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from PyQt6.QtCore import QCoreApplication

from models.settings import AppSettings
from core.npm_cache import NpmCache
from app.app_controller import AppController

_app = QCoreApplication.instance() or QCoreApplication([])


class AppControllerPmTest(unittest.TestCase):
    def setUp(self) -> None:
        cfg = tempfile.TemporaryDirectory(); self.addCleanup(cfg.cleanup)
        env_vars = ("XDG_CONFIG_HOME", "APPDATA", "XDG_CACHE_HOME")
        backup = {v: os.environ.get(v) for v in env_vars}
        for v in env_vars:
            os.environ[v] = cfg.name

        def restore() -> None:
            for v, val in backup.items():
                if val is None:
                    os.environ.pop(v, None)
                else:
                    os.environ[v] = val

        self.addCleanup(restore)

        self.settings = AppSettings(); self.settings.load()
        self.appc = AppController(self.settings, NpmCache())
        self.addCleanup(self.appc.shutdown)

    def test_default_defaults_to_npm(self) -> None:
        self.assertEqual(self.appc.defaultPackageManager, "npm")

    def test_set_default_persists_and_signals(self) -> None:
        spy: list[int] = []
        self.appc.pmSettingsChanged.connect(lambda: spy.append(1))
        self.appc.setDefaultPackageManager("pnpm")
        self.assertEqual(self.appc.defaultPackageManager, "pnpm")
        self.assertEqual(len(spy), 1)
        reloaded = AppSettings(); reloaded.load()
        self.assertEqual(reloaded.default_package_manager, "pnpm")

    def test_set_default_invalid_is_noop(self) -> None:
        self.appc.setDefaultPackageManager("deno")
        self.assertEqual(self.appc.defaultPackageManager, "npm")

    def test_overrides_list_is_sorted_with_display_names(self) -> None:
        self.settings.package_manager_overrides = {"/z/proj": "bun", "/a/proj": "pnpm"}
        ov = self.appc.packageManagerOverrides
        self.assertEqual([o["path"] for o in ov], ["/a/proj", "/z/proj"])
        self.assertEqual(ov[0], {"path": "/a/proj", "manager": "pnpm", "name": "pnpm"})
        self.assertEqual(ov[1]["name"], "Bun")

    def test_remove_override(self) -> None:
        self.settings.set_package_manager_override("/a", "yarn")
        self.appc.removePackageManagerOverride("/a")
        self.assertEqual(self.appc.packageManagerOverrides, [])
        reloaded = AppSettings(); reloaded.load()
        self.assertEqual(reloaded.package_manager_overrides, {})

    def test_picker_pin_refreshes_overrides_list(self) -> None:
        # A per-folder pin made through the picker (Pm.choose) must refresh the
        # Settings panel — Pm and App share the settings object, but App still
        # needs its notify to fire. main.py wires overridesChanged -> pmSettingsChanged.
        from app.package_manager_controller import PackageManagerController
        pm = PackageManagerController(self.settings)
        pm.overridesChanged.connect(self.appc.pmSettingsChanged)
        spy: list[int] = []
        self.appc.pmSettingsChanged.connect(lambda: spy.append(1))

        pm.setProject("/tmp/demo-proj")
        pm.choose("pnpm", True)

        self.assertTrue(spy, "pmSettingsChanged should fire so the panel re-reads the list")
        self.assertEqual(self.appc.packageManagerOverrides,
                         [{"path": "/tmp/demo-proj", "manager": "pnpm", "name": "pnpm"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
