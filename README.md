> **This project was fully generated with [Claude Code](https://claude.ai/code).**

# Package.json Updater

A desktop app for keeping npm dependencies up to date. Open a `package.json`, see available patch / minor / major upgrades fetched live from the npm registry, and apply them in one click — without touching the terminal.

---

## Features

- **Three-column update view** — Patch, Minor, and Major upgrades shown side by side with the release age of each version
- **Constraint-type badge** — each row shows the version constraint type (Compatible `^`, Tilde `~`, Exact, Range, Wildcard, Local, Any)
- **Per-dependency update button** — click ↑ on any version to write that single change to disk immediately, no re-fetch required
- **Bulk updates** — select multiple packages with checkboxes and hit *Update Selected*, or use *Update All* with a configurable scope (Patch & Minor only, or all levels including Major)
- **npm result cache** — fetched registry data is cached to disk with a configurable TTL so subsequent opens are instant; the ↺ Refresh button always bypasses the cache
- **Version age filter** — hide versions published less than N days ago to avoid recently-yanked releases
- **Group filtering** — show only `dependencies`, `devDependencies`, or `overrides`
- **Hide up-to-date** — collapse rows that have no available upgrade
- **Recent files** — start screen remembers the last opened projects with last-checked timestamps
- **Light & dark theme** — toggle in the toolbar, persisted between sessions

---

## Requirements

- Python 3.11+
- PyQt6 ≥ 6.6
- requests ≥ 2.31
- packaging ≥ 23.0

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd package-json-updater

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running

```bash
python main.py
```

---

## Usage

1. Click **Open Folder** or **Open package.json** on the start screen (or use `⌘O` / `Ctrl+O`)
2. The app fetches the latest versions for every dependency from the npm registry
3. Upgrades appear colour-coded by bump level — **blue** patch, **green** minor, **amber** major
4. Click the **↑** button in any cell to apply that single upgrade immediately
5. Or tick the checkboxes and click **Update Selected** / **Update All**
6. Run `npm install` in your project directory to apply the written changes

### Settings

Open **⚙ Settings** in the toolbar to configure:

- **Minimum version age** — only show versions published at least N days ago (default: 0 — no filter)
- **Cache TTL** — how long fetched npm data is reused before going to the registry again (default: 24 hours; set to 0 to always fetch live)
- **Clear Cache Now** — immediately wipe all cached registry data

---

## Project structure

```
package-json-updater/
├── main.py                  # Entry point
├── assets/                  # SVG icons
├── core/
│   ├── npm_registry.py      # npm registry API calls
│   ├── npm_cache.py         # Disk-backed registry result cache
│   ├── package_json.py      # Read / write package.json
│   └── semver_utils.py      # Version comparison helpers
├── models/
│   ├── dependency.py        # DependencyInfo dataclass
│   └── settings.py          # Persistent app settings
├── ui/
│   ├── main_window.py       # Main window, theming, orchestration
│   ├── start_screen.py      # Start screen with recent files
│   ├── dependency_table.py  # QTableWidget subclass
│   ├── version_cell_widget.py  # Per-cell version + ↑ button widget
│   └── settings_page.py     # Settings page (stack page 2)
└── workers/
    └── fetch_worker.py      # QThread worker for npm registry fetches
```
