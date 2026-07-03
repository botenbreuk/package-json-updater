"""
Phase 3 tests: the exec sites resolve and drive the active package manager
instead of hardcoding npm.

Covers:
  * AppSettings.resolve_package_manager / active_package_manager
  * InstallController._invocation (install argv, per platform)
  * ProjectController._install_ran_externally (all lockfiles, incl. bun)

Run from the repo root with:

    python -m unittest tests.test_exec_wiring
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from core.package_manager import PackageManager
from models.settings import AppSettings

NPM = PackageManager.NPM
YARN = PackageManager.YARN
PNPM = PackageManager.PNPM
BUN = PackageManager.BUN


class ProjectDirMixin(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def touch(self, name: str) -> None:
        with open(os.path.join(self.dir, name), "w"):
            pass

    def set_mtime(self, name: str, ts: float) -> None:
        os.utime(os.path.join(self.dir, name), (ts, ts))


# ── settings-driven resolution ────────────────────────────────────────────

class TestManagerResolution(ProjectDirMixin):
    def _settings(self, *, default: str = "npm", overrides: dict | None = None) -> AppSettings:
        # In-memory only — no save()/load(), so this never touches disk.
        s = AppSettings()
        s.default_package_manager = default
        s.package_manager_overrides = dict(overrides or {})
        return s

    def test_override_wins_over_lockfile(self) -> None:
        self.touch("yarn.lock")
        s = self._settings(overrides={self.dir: "bun"})
        self.assertEqual(s.active_package_manager(self.dir), BUN)

    def test_single_lockfile(self) -> None:
        self.touch("pnpm-lock.yaml")
        self.assertEqual(self._settings().active_package_manager(self.dir), PNPM)

    def test_nothing_found_uses_default(self) -> None:
        s = self._settings(default="yarn")
        self.assertEqual(s.active_package_manager(self.dir), YARN)

    def test_ambiguous_prefers_default_when_it_is_a_candidate(self) -> None:
        self.touch("package-lock.json")
        self.touch("pnpm-lock.yaml")
        s = self._settings(default="pnpm")
        self.assertEqual(s.active_package_manager(self.dir), PNPM)

    def test_ambiguous_falls_back_to_first_candidate(self) -> None:
        self.touch("yarn.lock")
        self.touch("pnpm-lock.yaml")
        s = self._settings(default="npm")           # npm is not a candidate here
        self.assertEqual(s.active_package_manager(self.dir), YARN)   # first in enum order

    def test_resolve_exposes_ambiguity(self) -> None:
        self.touch("yarn.lock")
        self.touch("bun.lockb")
        result = self._settings().resolve_package_manager(self.dir)
        self.assertIsNone(result.manager)
        self.assertTrue(result.is_ambiguous)
        self.assertEqual(result.candidates, (YARN, BUN))


# ── install command construction ──────────────────────────────────────────

class TestInstallInvocation(unittest.TestCase):
    def test_posix_uses_manager_binary_and_install(self) -> None:
        from app.install_controller import InstallController
        for pm in PackageManager:
            with self.subTest(manager=pm.id):
                program, args = InstallController._invocation(pm, os.environ.get("PATH", ""))
                self.assertEqual(args, ["install"])
                # resolved to a full path or left as the bare binary name
                self.assertTrue(program == pm.binary or os.path.basename(program) == pm.binary)

    def test_windows_wraps_in_cmd(self) -> None:
        from app.install_controller import InstallController
        with mock.patch("app.install_controller.sys.platform", "win32"):
            program, args = InstallController._invocation(PNPM, "")
            self.assertEqual(program, "cmd.exe")
            self.assertEqual(args, ["/c", "pnpm", "install"])


# ── external-install detection (all lockfiles, including bun) ──────────────

class TestInstallRanExternally(ProjectDirMixin):
    def _pkg(self) -> str:
        return os.path.join(self.dir, "package.json")

    def test_bun_lockb_counts(self) -> None:
        from app.project_controller import ProjectController
        self.touch("package.json"); self.set_mtime("package.json", 1000)
        self.touch("bun.lockb");    self.set_mtime("bun.lockb", 2000)
        self.assertTrue(ProjectController._install_ran_externally(self._pkg()))

    def test_bun_text_lock_counts(self) -> None:
        from app.project_controller import ProjectController
        self.touch("package.json"); self.set_mtime("package.json", 1000)
        self.touch("bun.lock");     self.set_mtime("bun.lock", 2000)
        self.assertTrue(ProjectController._install_ran_externally(self._pkg()))

    def test_stale_lockfile_is_not_external(self) -> None:
        from app.project_controller import ProjectController
        self.touch("package.json");      self.set_mtime("package.json", 2000)
        self.touch("package-lock.json"); self.set_mtime("package-lock.json", 1000)
        self.assertFalse(ProjectController._install_ran_externally(self._pkg()))

    def test_no_lockfile_is_not_external(self) -> None:
        from app.project_controller import ProjectController
        self.touch("package.json")
        self.assertFalse(ProjectController._install_ran_externally(self._pkg()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
