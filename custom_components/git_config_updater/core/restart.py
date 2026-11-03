"""Does a set of changed files need a Home Assistant restart, or is a reload enough?

Conservative: anything not known to be reloadable needs a restart.

- `configuration.yaml` and anything under `custom_components/` need a restart.
- Paths matching the configured extra globs need a restart.
- Package files (YAML under the packages directory) are reloadable only if every top-level key, old
  and new, is a domain with a reload action.
- The UI-editor files (`automations.yaml`, `scripts.yaml`, `scenes.yaml`) are reloadable.
- Files under directories that are never loaded as configuration (dashboards, themes, blueprints,
  www, docs, ...) and non-YAML files outside `custom_components/` are reloadable.
- Any other YAML file may be `!include`d by configuration.yaml for any domain: restart.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatch

# Domains whose YAML Home Assistant can reload without a restart (each has a `reload` action or is
# covered by `homeassistant.reload_all`). Checked against the 2026.10 source.
RELOADABLE_DOMAINS = frozenset({
    "automation", "script", "scene", "template", "group", "timer", "schedule", "person", "zone",
    "input_boolean", "input_button", "input_datetime", "input_number", "input_select", "input_text",
    "rest_command", "shell_command", "intent_script", "command_line",
})

# Files the UI editors own; their domains reload.
RELOADABLE_FILES = frozenset({"automations.yaml", "scripts.yaml", "scenes.yaml"})

# Directories Home Assistant never loads as configuration YAML. YAML dashboards are re-read when
# their file changes, themes and blueprints reload.
RELOAD_ONLY_DIRS = (
    "dashboards/", "themes/", "blueprints/", "www/", "docs/", "tests/", "bin/", "esphome/",
    ".github/", ".ci/",
)

_TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", re.MULTILINE)


def top_level_keys(text: str | None) -> set[str]:
    """The top-level mapping keys of a YAML document (no full parse: tags like !include are fine)."""
    return set(_TOP_KEY.findall(text or ""))


@dataclass
class Verdict:
    needed: bool = False
    reasons: list[str] = field(default_factory=list)

    def add(self, reason: str) -> None:
        self.needed = True
        if reason not in self.reasons:
            self.reasons.append(reason)


def needs_restart(
    paths: Iterable[str],
    contents: Callable[[str], tuple[str | None, str | None]],
    packages_dir: str = "packages",
    extra_globs: Iterable[str] = (),
) -> Verdict:
    """`paths` are the changed files (both sides of a rename), `contents(path)` returns the file's
    (old, new) text or None where it doesn't exist."""
    verdict = Verdict()
    globs = [g.strip() for g in extra_globs if g and g.strip()]
    pkg = packages_dir.strip("/") + "/" if packages_dir else None
    for path in sorted(set(paths)):
        if any(fnmatch(path, g) for g in globs):
            verdict.add(f"{path} matches a restart rule")
        elif path == "configuration.yaml":
            verdict.add("configuration.yaml changed")
        elif path.startswith("custom_components/"):
            verdict.add(f"custom integration changed ({path.split('/')[1]})")
        elif path in RELOADABLE_FILES or path.startswith(RELOAD_ONLY_DIRS):
            continue
        elif not path.endswith((".yaml", ".yml")):
            continue
        elif pkg and path.startswith(pkg):
            old, new = contents(path)
            others = sorted((top_level_keys(old) | top_level_keys(new)) - RELOADABLE_DOMAINS)
            if others:
                verdict.add(f"{path}: {', '.join(others)} can't be reloaded")
        else:
            verdict.add(f"{path} may be included by configuration.yaml")
    return verdict
