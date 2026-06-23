NL: dict[str, str] = {
    # ── Toolbar / navigation ───────────────────────────────────────────────────
    "←  Back":                  "←  Terug",
    "✕  Close":                 "✕  Sluiten",
    "↺  Hard Refresh":          "↺  Volledig vernieuwen",
    "📦  npm install":          "📦  npm install",
    "⚠  Old only":              "⚠  Alleen oud",
    "📁  Open Folder":          "📁  Map openen",
    "📂  Open package.json":    "📂  package.json openen",
    "↺  Refresh":               "↺  Vernieuwen",
    "⚙  Settings":              "⚙  Instellingen",

    # ── Time units ────────────────────────────────────────────────────────────
    " day":     " dag",
    " days":    " dagen",
    " hours":   " uur",
    " week":    " week",
    " weeks":   " weken",
    "months":   "maanden",
    "years":    "jaren",

    # ── Git ───────────────────────────────────────────────────────────────────
    "↓ Pull":           "↓ Ophalen",
    "git pull failed":  "git pull mislukt",
    "Pulling…":         "Ophalen…",

    # ── Settings navigation ───────────────────────────────────────────────────
    "About":                "Over",
    "Display":              "Weergave",
    "General":              "Algemeen",
    "Language":             "Taal",
    "Old Version Warning":  "Versiewaarschuwing",
    "Settings":             "Instellingen",
    "Theme":                "Thema",
    "Version Age Filter":   "Leeftijdsfilter",
    "Version Cache":        "Versiecache",

    # ── Theme ─────────────────────────────────────────────────────────────────
    "Dark":             "Donker",
    "Light":            "Licht",
    "System default":   "Systeemstandaard",
    "System default follows your OS light/dark preference.":
        "De systeemstandaard volgt de licht-/donkermodus van je besturingssysteem.",

    # ── Language ──────────────────────────────────────────────────────────────
    "Dutch":    "Nederlands",
    "English":  "Engels",
    "System default uses your OS language.":
        "De systeemstandaard gebruikt de taal van je besturingssysteem.",

    # ── Table columns ─────────────────────────────────────────────────────────
    "Current":          "Huidig",
    "Group":            "Groep",
    "Major ↑":          "Major ↑",
    "Minor ↑":          "Minor ↑",
    "Minor / Patch ↑":  "Minor / Patch ↑",
    "Package":          "Pakket",
    "Patch ↑":          "Patch ↑",
    "Patch / Minor":        "Patch / Minor",
    "Patch / Minor only":   "Alleen Patch / Minor",
    "Type":             "Type",

    # ── Filters ───────────────────────────────────────────────────────────────
    "All (including Major)":    "Alles (inclusief Major)",
    "All groups":               "Alle groepen",
    "All incl. Major":          "Alles incl. Major",
    "Hide up-to-date":          "Verberg bijgewerkte",
    "Show:":                    "Toon:",

    # ── Buttons / actions ─────────────────────────────────────────────────────
    "Cancel":               "Annuleren",
    "Clear all":            "Alles wissen",
    "Close":                "Sluiten",
    "OK":                   "OK",
    "Remove from recents":  "Verwijder uit recenten",
    "Save":                 "Opslaan",
    "Update":               "Bijwerken",

    # ── Dialogs ───────────────────────────────────────────────────────────────
    "All files (*)":                        "Alle bestanden (*)",
    "Confirm Update All":                   "Bevestig alles bijwerken",
    "Open Folder containing package.json":  "Map met package.json openen",
    "Open package.json":                    "package.json openen",
    "package.json (package.json)":          "package.json (package.json)",

    # ── Status / info ─────────────────────────────────────────────────────────
    "All packages are up to date":  "Alle pakketten zijn bijgewerkt",
    "Error":                        "Fout",
    "Loading…":                     "Laden…",
    "No file loaded. Open a package.json to begin.":
        "Geen bestand geladen. Open een package.json om te beginnen.",
    "No recent files.":     "Geen recente bestanden.",
    "Output":               "Uitvoer",
    "pending":              "in behandeling",
    "RECENT":               "RECENT",

    # ── Strings with placeholders ─────────────────────────────────────────────
    "in %1":                    "over %1",
    "Installed version is %1 old — consider updating":
        "Geïnstalleerde versie is %1 oud — overweeg een update",
    "node …":       "node …",
    "node %1":      "node %1",
    "npm …":        "npm …",
    "npm %1":       "npm %1",
    "npm install":  "npm install",
    "Version %1":   "Versie %1",
    "Update to %1":             "Bijwerken naar %1",
    "Update All  ·  %1":        "Alles bijwerken  ·  %1",
    "Update Selected  ·  %1":   "Geselecteerde bijwerken  ·  %1",
    "Update %1 package(s) using mode: %2?\nThis will overwrite your package.json.":
        "%1 pakket(ten) bijwerken met modus: %2?\nDit overschrijft je package.json.",

    # ── Version Age Filter settings ───────────────────────────────────────────
    "Minimum age:":         "Minimumleeftijd:",
    "No filter (0 days)":   "Geen filter (0 dagen)",
    "Only show package versions published at least this many days ago. "
    "Helps avoid recently published packages that might be reverted. "
    "Set to 0 to disable the filter.":
        "Toon alleen pakketversies die minstens dit aantal dagen geleden zijn gepubliceerd. "
        "Helpt recent gepubliceerde pakketten te vermijden die mogelijk worden teruggedraaid. "
        "Stel 0 in om het filter uit te schakelen.",

    # ── Old Version Warning settings ──────────────────────────────────────────
    "Disabled":     "Uitgeschakeld",
    "Warn after:":  "Waarschuw na:",
    "Show a ⚠ warning next to the installed version when it has not been updated "
    "for longer than this threshold. Set to 0 to disable.":
        "Toon een ⚠-waarschuwing naast de geïnstalleerde versie als deze langer dan "
        "de drempelwaarde niet is bijgewerkt. Stel 0 in om uit te schakelen.",

    # ── Version Cache settings ────────────────────────────────────────────────
    "Cache TTL:":   "Cache-TTL:",
    "Cached results make subsequent opens instant. "
    "Use ↺ Refresh to always get the latest versions regardless of this setting.":
        "Gecachede resultaten maken vervolgopeningen direct. "
        "Gebruik ↺ Vernieuwen om altijd de nieuwste versies op te halen, "
        "ongeacht deze instelling.",
    "Clear cache?":     "Cache wissen?",
    "Clear Cache":      "Cache wissen",
    "Clear Cache Now":  "Cache nu wissen",
    "Delete all locally stored version data. The next time you open a project "
    "all package information will be re-fetched fresh from the npm registry.":
        "Verwijder alle lokaal opgeslagen versiegegevens. De volgende keer dat je "
        "een project opent, worden alle pakketgegevens vers opgehaald uit het npm-register.",
    "All locally stored npm version data will be deleted. The next time you open "
    "a project every package will be re-fetched from the npm registry.":
        "Alle lokaal opgeslagen npm-versiegegevens worden verwijderd. De volgende keer "
        "dat je een project opent, worden alle pakketten opnieuw opgehaald uit het npm-register.",

    # ── Display settings ──────────────────────────────────────────────────────
    "Customize how version updates are shown in the table.":
        "Pas aan hoe versie-updates in de tabel worden weergegeven.",
    "Merge Patch and Minor":        "Patch en Minor samenvoegen",
    "Merge Patch and Minor updates": "Patch- en Minor-updates samenvoegen",
    "When enabled, the Patch and Minor columns are merged into one. "
    "The highest available update between the two is shown.":
        "Indien ingeschakeld, worden de Patch- en Minor-kolommen samengevoegd tot één. "
        "De hoogste beschikbare update van de twee wordt getoond.",

    # ── About ─────────────────────────────────────────────────────────────────
    "Check and update npm dependencies":    "Controleer en werk npm-afhankelijkheden bij",
    "Package.json Updater":                 "Package.json Updater",
}
