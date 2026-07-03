"""
Phase 4 tests: the PackageManagerController (QML `Pm`) — prompting on
ambiguity, applying a choice, persisting a per-folder pin, and reporting the
detected lockfiles.

Signals are delivered synchronously to Python slots (direct connections), so a
QCoreApplication is enough — no event loop needed.  Storage is isolated to a
temp config dir so nothing touches the developer's real settings.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from PyQt6.QtCore import QCoreApplication

from models.settings import AppSettings
from app.package_manager_controller import PackageManagerController

_app = QCoreApplication.instance() or QCoreApplication([])


class PmControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        proj = tempfile.TemporaryDirectory(); self.addCleanup(proj.cleanup)
        cfg = tempfile.TemporaryDirectory();  self.addCleanup(cfg.cleanup)
        self.proj = proj.name

        backup = {v: os.environ.get(v) for v in ("XDG_CONFIG_HOME", "APPDATA")}
        for v in backup:
            os.environ[v] = cfg.name

        def restore() -> None:
            for v, val in backup.items():
                if val is None:
                    os.environ.pop(v, None)
                else:
                    os.environ[v] = val

        self.addCleanup(restore)

    def touch(self, name: str) -> None:
        with open(os.path.join(self.proj, name), "w"):
            pass

    # ── prompting ──────────────────────────────────────────────────────────

    def test_ambiguous_open_prompts_once(self) -> None:
        self.touch("package-lock.json")
        self.touch("pnpm-lock.yaml")
        pm = PackageManagerController(AppSettings())
        seen: list[str] = []
        pm.showPicker.connect(lambda cid: seen.append(cid))
        pm.setProject(self.proj)
        self.assertEqual(len(seen), 1)

    def test_single_lockfile_does_not_prompt(self) -> None:
        self.touch("yarn.lock")
        pm = PackageManagerController(AppSettings())
        seen: list[str] = []
        pm.showPicker.connect(lambda cid: seen.append(cid))
        pm.setProject(self.proj)
        self.assertEqual(seen, [])
        self.assertEqual(pm.activeId, "yarn")
        self.assertEqual(pm.installCommand, "yarn install")

    def test_same_dir_does_not_reprompt(self) -> None:
        self.touch("package-lock.json")
        self.touch("bun.lockb")
        pm = PackageManagerController(AppSettings())
        seen: list[str] = []
        pm.showPicker.connect(lambda cid: seen.append(cid))
        pm.setProject(self.proj)
        pm.setProject(self.proj)          # e.g. re-emitted projectChanged after a bulk update
        self.assertEqual(len(seen), 1)

    # ── choosing ───────────────────────────────────────────────────────────

    def test_choose_remember_persists_and_wins_next_open(self) -> None:
        self.touch("package-lock.json")
        self.touch("pnpm-lock.yaml")
        settings = AppSettings()
        pm = PackageManagerController(settings)
        pm.setProject(self.proj)
        changed: list[str] = []
        pm.activeChanged.connect(lambda: changed.append(pm.activeId))

        pm.choose("pnpm", True)
        self.assertEqual(pm.activeId, "pnpm")
        self.assertEqual(pm.installCommand, "pnpm install")
        self.assertTrue(pm.hasOverride)
        self.assertTrue(changed)

        # a fresh controller over the reloaded settings resolves straight to pnpm
        reloaded = AppSettings(); reloaded.load()
        pm2 = PackageManagerController(reloaded)
        seen: list[str] = []
        pm2.showPicker.connect(lambda cid: seen.append(cid))
        pm2.setProject(self.proj)
        self.assertEqual(pm2.activeId, "pnpm")
        self.assertEqual(seen, [])         # no prompt — the pin resolved it

    def test_choose_one_off_does_not_persist(self) -> None:
        self.touch("yarn.lock")
        settings = AppSettings()
        pm = PackageManagerController(settings)
        pm.setProject(self.proj)
        pm.choose("bun", False)
        self.assertEqual(pm.activeId, "bun")
        self.assertFalse(pm.hasOverride)
        self.assertIsNone(settings.package_manager_override(self.proj))

    def test_invalid_choice_is_ignored(self) -> None:
        self.touch("yarn.lock")
        pm = PackageManagerController(AppSettings())
        pm.setProject(self.proj)
        pm.choose("deno", True)
        self.assertEqual(pm.activeId, "yarn")   # unchanged

    # ── introspection ──────────────────────────────────────────────────────

    def test_detected_lockfiles(self) -> None:
        self.touch("yarn.lock")
        self.touch("bun.lockb")
        pm = PackageManagerController(AppSettings())
        pm.setProject(self.proj)
        self.assertEqual(pm.detectedLockfiles(), {"yarn": "yarn.lock", "bun": "bun.lockb"})

    def test_detected_lockfiles_empty_without_project(self) -> None:
        pm = PackageManagerController(AppSettings())
        self.assertEqual(pm.detectedLockfiles(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
