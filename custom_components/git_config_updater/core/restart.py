"""Does a set of changed files need a Home Assistant restart, or is a reload enough?

Conservative: anything not known to be reloadable needs a restart.

- Paths matching the configured restart globs need a restart.
- `configuration.yaml` and anything under `custom_components/` need a restart.
- Paths matching the configured reload globs (files Home Assistant never loads) are reloadable.
- Package files (YAML under the packages directory) are parsed. Each top-level section that changed
  must be reloadable: a domain with a reload action, or an entity domain (`sensor`, `light`, ...)
  whose every entry uses a platform with a reload action. A file that can't be parsed needs a restart.
- The UI-editor files (`automations.yaml`, `scripts.yaml`, `scenes.yaml`) are reloadable.
- Files under directories that are never loaded as configuration (dashboards, themes, blueprints,
  www, docs, ...), dotfiles and dot-directories at the top, and non-YAML files outside
  `custom_components/` are reloadable.
- Any other YAML file may be `!include`d by configuration.yaml for any domain: restart.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

import yaml

# Domains whose YAML Home Assistant can reload without a restart (each has a `reload` action that
# `homeassistant.reload_all` calls). Checked against the 2026.10 source.
RELOADABLE_DOMAINS = frozenset({
    "automation", "script", "scene", "template", "group", "timer", "schedule", "person", "zone",
    "input_boolean", "input_button", "input_datetime", "input_number", "input_select", "input_text",
    "rest_command", "shell_command", "intent_script", "command_line", "rest",
})

# Entity domains configured as a list of `- platform: x` entries. Such a section is reloadable when
# every entry's platform is in RELOADABLE_PLATFORMS. `notify` is left out on purpose:
# `reload_all` skips it.
PLATFORM_DOMAINS = frozenset({
    "sensor", "binary_sensor", "light", "switch", "cover", "fan", "lock", "climate", "media_player",
    "camera", "alarm_control_panel", "weather", "vacuum", "water_heater", "humidifier", "siren",
    "valve", "number", "select", "button", "image", "event", "text", "date", "time", "datetime",
})

# Integrations whose `reload` action reloads their YAML platforms. Checked against the 2026.10
# source (integrations with a `reload` action in services.yaml).
RELOADABLE_PLATFORMS = frozenset({
    "bayesian", "derivative", "filter", "generic", "generic_thermostat", "group", "history_stats",
    "min_max", "rest", "statistics", "template", "trend", "universal",
})

# Files the UI editors own; their domains reload.
RELOADABLE_FILES = frozenset({"automations.yaml", "scripts.yaml", "scenes.yaml"})

# Directories Home Assistant never loads as configuration YAML. YAML dashboards are re-read when
# their file changes, themes and blueprints reload.
RELOAD_ONLY_DIRS = (
    "dashboards/", "themes/", "blueprints/", "www/", "docs/", "tests/", "bin/", "esphome/",
)


@dataclass
class Tagged:
    """A YAML value behind a tag such as `!include` or `!secret`, kept unresolved."""

    tag: str
    value: Any


class _Loader(yaml.SafeLoader):
    """A safe loader that keeps Home Assistant's tags as `Tagged` values instead of failing."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        # Like libyaml (which Home Assistant uses), allow an anchor to be redefined: the later one
        # wins. PyYAML's pure-Python composer would reject the file.
        event = self.peek_event()
        if not isinstance(event, yaml.AliasEvent) and getattr(event, "anchor", None) is not None:
            self.anchors.pop(event.anchor, None)
        return super().compose_node(parent, index)


def _tagged(loader: _Loader, suffix: str, node: yaml.Node) -> Tagged:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)  # type: ignore[arg-type]
    return Tagged(f"!{suffix}", value)


_Loader.add_multi_constructor("!", _tagged)


def package_sections(text: str | None) -> dict[Any, Any] | None:
    """The top-level sections of a package file, {} for a missing or empty one, None if it isn't a
    YAML mapping."""
    if not text:
        return {}
    try:
        data = yaml.load(text, Loader=_Loader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError:
        return None
    if data is None:
        return {}
    return data if isinstance(data, dict) else None


def _domain(key: Any) -> str:
    """`sensor living` is the `sensor` domain (Home Assistant allows a label after the domain)."""
    return str(key).split()[0] if str(key).split() else str(key)


def _unreloadable(domain: str, value: Any) -> str | None:
    """None if the section reloads, else a label for the reason."""
    if domain in RELOADABLE_DOMAINS:
        return None
    if domain not in PLATFORM_DOMAINS:
        return domain
    if value is None:
        return None
    entries = value if isinstance(value, list) else [value]
    bad = set()
    for entry in entries:
        platform = entry.get("platform") if isinstance(entry, dict) else None
        if not isinstance(platform, str):
            return domain  # an !include or an entry without a platform: unknown
        if platform not in RELOADABLE_PLATFORMS:
            bad.add(platform)
    return f"{domain} ({', '.join(sorted(bad))})" if bad else None


_MISSING = object()


def _package_reasons(path: str, old: str | None, new: str | None) -> list[str]:
    before, after = package_sections(old), package_sections(new)
    if before is None or after is None:
        return [f"{path} couldn't be read as a package"]
    labels = set()
    for key in before.keys() | after.keys():
        sides = [before.get(key, _MISSING), after.get(key, _MISSING)]
        if sides[0] == sides[1]:
            continue  # unchanged section
        for value in sides:
            if value is not _MISSING and (label := _unreloadable(_domain(key), value)):
                labels.add(label)
    return [f"{path}: {', '.join(sorted(labels))} can't be reloaded"] if labels else []


@dataclass
class Verdict:
    needed: bool = False
    reasons: list[str] = field(default_factory=list)

    def add(self, reason: str) -> None:
        self.needed = True
        if reason not in self.reasons:
            self.reasons.append(reason)


def _globs(raw: Iterable[str]) -> list[str]:
    return [g.strip() for g in raw if g and g.strip()]


def needs_restart(
    paths: Iterable[str],
    contents: Callable[[str], tuple[str | None, str | None]],
    packages_dir: str = "packages",
    extra_globs: Iterable[str] = (),
    reload_globs: Iterable[str] = (),
) -> Verdict:
    """`paths` are the changed files (both sides of a rename), `contents(path)` returns the file's
    (old, new) text or None where it doesn't exist. `extra_globs` force a restart, `reload_globs`
    mark files Home Assistant never loads."""
    verdict = Verdict()
    restart, reload = _globs(extra_globs), _globs(reload_globs)
    pkg = packages_dir.strip("/") + "/" if packages_dir and packages_dir.strip("/") else None
    for path in sorted(set(paths)):
        if any(fnmatch(path, g) for g in restart):
            verdict.add(f"{path} matches a restart rule")
        elif path == "configuration.yaml":
            verdict.add("configuration.yaml changed")
        elif path.startswith("custom_components/"):
            verdict.add(f"custom integration changed ({path.split('/')[1]})")
        elif any(fnmatch(path, g) for g in reload):
            continue
        elif path in RELOADABLE_FILES or path.startswith(RELOAD_ONLY_DIRS) or path.startswith("."):
            continue
        elif not path.endswith((".yaml", ".yml")):
            continue
        elif pkg and path.startswith(pkg):
            for reason in _package_reasons(path, *contents(path)):
                verdict.add(reason)
        else:
            verdict.add(f"{path} may be included by configuration.yaml")
    return verdict
