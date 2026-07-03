"""
Unit tests for core.package_manager — the manager abstraction and detection.

Pure stdlib (unittest); run from the repo root with:

    python -m unittest tests.test_package_manager
    python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from core.package_manager import (
    DEFAULT_MANAGER,
    Detection,
    DetectionSource,
    PackageManager,
    detect,
)

NPM = PackageManager.NPM
YARN = PackageManager.YARN
PNPM = PackageManager.PNPM
BUN = PackageManager.BUN


class ProjectDirMixin(unittest.TestCase):
    """Gives each test an isolated temp project directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def touch(self, name: str, *, in_dir: str | None = None) -> None:
        path = os.path.join(in_dir or self.dir, name)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8"):
            pass

    def write_package_json(self, obj, *, in_dir: str | None = None) -> None:
        path = os.path.join(in_dir or self.dir, "package.json")
        with open(path, "w", encoding="utf-8") as fh:
            if isinstance(obj, str):
                fh.write(obj)
            else:
                json.dump(obj, fh)

    def subdir(self, *parts: str) -> str:
        path = os.path.join(self.dir, *parts)
        os.makedirs(path, exist_ok=True)
        return path


# ── metadata & command builders ───────────────────────────────────────────

class TestMetadata(unittest.TestCase):
    def test_ids_display_and_binary(self) -> None:
        self.assertEqual(NPM.id, "npm")
        self.assertEqual(YARN.id, "yarn")
        self.assertEqual(PNPM.id, "pnpm")
        self.assertEqual(BUN.id, "bun")
        self.assertEqual((NPM.display, YARN.display, PNPM.display, BUN.display),
                         ("npm", "Yarn", "pnpm", "Bun"))
        for pm in PackageManager:
            self.assertEqual(pm.binary, pm.id)

    def test_lockfile_map(self) -> None:
        self.assertEqual(NPM.lockfiles, ("package-lock.json", "npm-shrinkwrap.json"))
        self.assertEqual(YARN.lockfiles, ("yarn.lock",))
        self.assertEqual(PNPM.lockfiles, ("pnpm-lock.yaml",))
        self.assertEqual(BUN.lockfiles, ("bun.lock", "bun.lockb"))

    def test_enum_order_is_npm_first(self) -> None:
        self.assertEqual(list(PackageManager), [NPM, YARN, PNPM, BUN])

    def test_default_manager_is_npm(self) -> None:
        self.assertIs(DEFAULT_MANAGER, NPM)


class TestFromId(unittest.TestCase):
    def test_known_ids(self) -> None:
        self.assertIs(PackageManager.from_id("npm"), NPM)
        self.assertIs(PackageManager.from_id("yarn"), YARN)
        self.assertIs(PackageManager.from_id("pnpm"), PNPM)
        self.assertIs(PackageManager.from_id("bun"), BUN)

    def test_case_insensitive_and_whitespace(self) -> None:
        self.assertIs(PackageManager.from_id("  PNPM  "), PNPM)
        self.assertIs(PackageManager.from_id("Yarn"), YARN)

    def test_passthrough_instance(self) -> None:
        self.assertIs(PackageManager.from_id(BUN), BUN)

    def test_unknown_and_empty(self) -> None:
        for bad in (None, "", "   ", "cnpm", "npmx", "deno"):
            self.assertIsNone(PackageManager.from_id(bad))


class TestCommandBuilders(unittest.TestCase):
    def test_install(self) -> None:
        self.assertEqual(NPM.install_cmd(), ["npm", "install"])
        self.assertEqual(YARN.install_cmd(), ["yarn", "install"])
        self.assertEqual(PNPM.install_cmd(), ["pnpm", "install"])
        self.assertEqual(BUN.install_cmd(), ["bun", "install"])

    def test_clean_install(self) -> None:
        self.assertEqual(NPM.clean_install_cmd(), ["npm", "ci"])
        self.assertEqual(YARN.clean_install_cmd(), ["yarn", "install", "--immutable"])
        self.assertEqual(PNPM.clean_install_cmd(), ["pnpm", "install", "--frozen-lockfile"])
        self.assertEqual(BUN.clean_install_cmd(), ["bun", "install", "--frozen-lockfile"])

    def test_version(self) -> None:
        for pm in PackageManager:
            self.assertEqual(pm.version_cmd(), [pm.binary, "--version"])

    def test_add_with_version(self) -> None:
        self.assertEqual(NPM.add_cmd("left-pad", "1.3.0"), ["npm", "install", "left-pad@1.3.0"])
        self.assertEqual(YARN.add_cmd("left-pad", "1.3.0"), ["yarn", "add", "left-pad@1.3.0"])
        self.assertEqual(PNPM.add_cmd("left-pad", "1.3.0"), ["pnpm", "add", "left-pad@1.3.0"])
        self.assertEqual(BUN.add_cmd("left-pad", "1.3.0"), ["bun", "add", "left-pad@1.3.0"])

    def test_add_without_version(self) -> None:
        self.assertEqual(NPM.add_cmd("left-pad"), ["npm", "install", "left-pad"])
        self.assertEqual(PNPM.add_cmd("left-pad"), ["pnpm", "add", "left-pad"])


# ── detection: single lockfile (the common case) ──────────────────────────

class TestDetectSingleLockfile(ProjectDirMixin):
    def test_each_lockfile_resolves(self) -> None:
        cases = {
            "package-lock.json": NPM,
            "npm-shrinkwrap.json": NPM,
            "yarn.lock": YARN,
            "pnpm-lock.yaml": PNPM,
            "bun.lock": BUN,
            "bun.lockb": BUN,
        }
        for lockfile, expected in cases.items():
            with self.subTest(lockfile=lockfile), tempfile.TemporaryDirectory() as d:
                with open(os.path.join(d, lockfile), "w"):
                    pass
                result = detect(d)
                self.assertEqual(result.manager, expected)
                self.assertEqual(result.source, DetectionSource.LOCKFILE)
                self.assertEqual(result.candidates, (expected,))
                self.assertEqual(result.lockfile_dir, os.path.abspath(d))
                self.assertFalse(result.is_ambiguous)

    def test_two_bun_lockfiles_still_single_candidate(self) -> None:
        self.touch("bun.lock")
        self.touch("bun.lockb")
        result = detect(self.dir)
        self.assertEqual(result.manager, BUN)
        self.assertEqual(result.candidates, (BUN,))
        self.assertEqual(result.source, DetectionSource.LOCKFILE)


# ── detection: ambiguity ──────────────────────────────────────────────────

class TestDetectAmbiguous(ProjectDirMixin):
    def test_two_managers_prompt(self) -> None:
        self.touch("package-lock.json")
        self.touch("pnpm-lock.yaml")
        result = detect(self.dir)
        self.assertIsNone(result.manager)
        self.assertTrue(result.is_ambiguous)
        self.assertEqual(result.source, DetectionSource.AMBIGUOUS)
        self.assertEqual(result.candidates, (NPM, PNPM))

    def test_candidates_are_in_enum_order(self) -> None:
        # Create in a deliberately "wrong" order to prove ordering is stable.
        self.touch("bun.lockb")
        self.touch("yarn.lock")
        self.touch("package-lock.json")
        result = detect(self.dir)
        self.assertEqual(result.candidates, (NPM, YARN, BUN))

    def test_all_four(self) -> None:
        for lf in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb"):
            self.touch(lf)
        result = detect(self.dir)
        self.assertTrue(result.is_ambiguous)
        self.assertEqual(result.candidates, (NPM, YARN, PNPM, BUN))


# ── detection: precedence ─────────────────────────────────────────────────

class TestDetectPrecedence(ProjectDirMixin):
    def test_override_beats_everything(self) -> None:
        self.touch("yarn.lock")
        self.write_package_json({"packageManager": "pnpm@9.1.0"})
        result = detect(self.dir, override="bun")
        self.assertEqual(result.manager, BUN)
        self.assertEqual(result.source, DetectionSource.OVERRIDE)
        self.assertEqual(result.candidates, ())

    def test_override_accepts_instance(self) -> None:
        result = detect(self.dir, override=PNPM)
        self.assertEqual(result.manager, PNPM)
        self.assertEqual(result.source, DetectionSource.OVERRIDE)

    def test_unknown_override_is_ignored(self) -> None:
        self.touch("yarn.lock")
        result = detect(self.dir, override="cnpm")
        self.assertEqual(result.manager, YARN)
        self.assertEqual(result.source, DetectionSource.LOCKFILE)

    def test_package_json_field_beats_lockfile(self) -> None:
        self.touch("yarn.lock")
        self.write_package_json({"packageManager": "pnpm@9.1.0"})
        result = detect(self.dir)
        self.assertEqual(result.manager, PNPM)
        self.assertEqual(result.source, DetectionSource.PACKAGE_JSON_FIELD)

    def test_package_json_field_with_hash(self) -> None:
        self.write_package_json({"packageManager": "yarn@4.1.0+sha256.deadbeef"})
        result = detect(self.dir)
        self.assertEqual(result.manager, YARN)
        self.assertEqual(result.source, DetectionSource.PACKAGE_JSON_FIELD)

    def test_package_json_field_without_version(self) -> None:
        self.write_package_json({"packageManager": "bun"})
        self.assertEqual(detect(self.dir).manager, BUN)

    def test_unknown_field_falls_through_to_lockfile(self) -> None:
        self.touch("pnpm-lock.yaml")
        self.write_package_json({"packageManager": "corepack@1.0.0"})
        result = detect(self.dir)
        self.assertEqual(result.manager, PNPM)
        self.assertEqual(result.source, DetectionSource.LOCKFILE)

    def test_field_absent_uses_lockfile(self) -> None:
        self.touch("pnpm-lock.yaml")
        self.write_package_json({"name": "demo", "version": "1.0.0"})
        self.assertEqual(detect(self.dir).source, DetectionSource.LOCKFILE)


# ── detection: fallback ───────────────────────────────────────────────────

class TestDetectFallback(ProjectDirMixin):
    def test_nothing_found_defaults_to_npm(self) -> None:
        self.write_package_json({"name": "demo"})
        result = detect(self.dir)
        self.assertEqual(result.manager, NPM)
        self.assertEqual(result.source, DetectionSource.DEFAULT)
        self.assertEqual(result.candidates, ())
        self.assertIsNone(result.lockfile_dir)

    def test_custom_default_is_respected(self) -> None:
        result = detect(self.dir, default="pnpm")
        self.assertEqual(result.manager, PNPM)
        self.assertEqual(result.source, DetectionSource.DEFAULT)

    def test_custom_default_accepts_instance(self) -> None:
        self.assertEqual(detect(self.dir, default=BUN).manager, BUN)

    def test_bad_default_falls_back_to_npm(self) -> None:
        self.assertEqual(detect(self.dir, default="nonsense").manager, NPM)

    def test_empty_project_dir_defaults(self) -> None:
        result = detect("", default="yarn")
        self.assertEqual(result.manager, YARN)
        self.assertEqual(result.source, DetectionSource.DEFAULT)

    def test_empty_project_dir_still_honors_override(self) -> None:
        result = detect("", override="bun")
        self.assertEqual(result.manager, BUN)
        self.assertEqual(result.source, DetectionSource.OVERRIDE)


# ── detection: monorepo walk-up ───────────────────────────────────────────

class TestDetectMonorepo(ProjectDirMixin):
    def test_lockfile_found_in_parent(self) -> None:
        self.touch("pnpm-lock.yaml")                     # repo root == self.dir
        pkg = self.subdir("packages", "app")             # nested package
        self.write_package_json({"name": "app"}, in_dir=pkg)
        result = detect(pkg)
        self.assertEqual(result.manager, PNPM)
        self.assertEqual(result.source, DetectionSource.LOCKFILE)
        self.assertEqual(result.lockfile_dir, os.path.abspath(self.dir))

    def test_nearest_lockfile_wins_over_ancestor(self) -> None:
        self.touch("pnpm-lock.yaml")                     # root
        pkg = self.subdir("packages", "app")
        self.touch("yarn.lock", in_dir=pkg)              # closer lockfile
        result = detect(pkg)
        self.assertEqual(result.manager, YARN)
        self.assertEqual(result.lockfile_dir, os.path.abspath(pkg))

    def test_ambiguity_detected_at_the_nearest_level(self) -> None:
        pkg = self.subdir("packages", "app")
        self.touch("package-lock.json", in_dir=pkg)
        self.touch("bun.lockb", in_dir=pkg)
        result = detect(pkg)
        self.assertTrue(result.is_ambiguous)
        self.assertEqual(result.candidates, (NPM, BUN))


# ── detection: robustness ─────────────────────────────────────────────────

class TestDetectRobustness(ProjectDirMixin):
    def test_malformed_package_json_is_ignored(self) -> None:
        self.write_package_json("{ this is not valid json ")
        self.touch("yarn.lock")
        result = detect(self.dir)
        self.assertEqual(result.manager, YARN)      # fell through cleanly
        self.assertEqual(result.source, DetectionSource.LOCKFILE)

    def test_non_object_package_json_is_ignored(self) -> None:
        self.write_package_json("[1, 2, 3]")
        result = detect(self.dir)
        self.assertEqual(result.source, DetectionSource.DEFAULT)

    def test_non_string_field_is_ignored(self) -> None:
        self.write_package_json({"packageManager": {"name": "pnpm"}})
        result = detect(self.dir)
        self.assertEqual(result.source, DetectionSource.DEFAULT)

    def test_nonexistent_directory_defaults(self) -> None:
        missing = os.path.join(self.dir, "does", "not", "exist")
        result = detect(missing)
        self.assertEqual(result.manager, NPM)
        self.assertEqual(result.source, DetectionSource.DEFAULT)

    def test_detection_result_is_frozen(self) -> None:
        result = detect(self.dir)
        self.assertIsInstance(result, Detection)
        with self.assertRaises(Exception):
            result.manager = YARN  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main(verbosity=2)
