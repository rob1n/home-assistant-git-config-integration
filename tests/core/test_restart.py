from custom_components.git_config_updater.core.restart import Tagged, needs_restart, package_sections


def contents(table):
    return lambda p: table.get(p, (None, None))


def package(old, new, **kw):
    return needs_restart(["packages/p.yaml"], contents({"packages/p.yaml": (old, new)}), **kw)


def test_package_sections_keep_tags():
    text = "# comment\ninput_boolean:\n  a:\n    name: !secret a_name\ntemplate: !include t.yaml\n"
    assert package_sections(text) == {"input_boolean": {"a": {"name": Tagged("!secret", "a_name")}},
                                      "template": Tagged("!include", "t.yaml")}
    assert package_sections(None) == {} and package_sections("# only a comment\n") == {}
    assert package_sections("- a list\n") is None and package_sections("a: [broken\n") is None
    # A redefined anchor is fine (libyaml, which Home Assistant uses, allows it).
    assert package_sections("a: &x 1\nb: *x\nc: &x 2\nd: *x\n") == {"a": 1, "b": 1, "c": 2, "d": 2}


def test_configuration_and_custom_components_need_restart():
    v = needs_restart(["configuration.yaml", "custom_components/foo/sensor.py"], contents({}))
    assert v.needed
    assert "configuration.yaml changed" in v.reasons
    assert "custom integration changed (foo)" in v.reasons


def test_reloadable_package():
    assert not package("input_boolean:\n  a: {}\n", "input_boolean:\n  a: {}\nscript:\n  b: {}\n").needed


def test_package_with_non_reloadable_domain():
    v = package(None, "sensor:\n  - platform: statistics\ncounter:\n  c: {}\n")
    assert v.reasons == ["packages/p.yaml: counter can't be reloaded"]


def test_removed_non_reloadable_domain_also_counts():
    assert package("powercalc:\n  a: 1\n", None).needed


def test_labelled_domain_keys_count():
    # Home Assistant allows `<domain> <label>:`; the domain is the first word.
    v = package(None, "sensor living:\n  - platform: systemmonitor\n")
    assert v.reasons == ["packages/p.yaml: sensor (systemmonitor) can't be reloaded"]
    assert not package(None, "automation kitchen:\n  - alias: a\n").needed


def test_reloadable_platforms():
    text = ("binary_sensor:\n  - platform: bayesian\n    observations:\n      - platform: state\n"
            "light:\n  - platform: group\n    entities: []\n"
            "sensor:\n  - name: avg\n    platform: statistics\n")
    assert not package(None, text).needed


def test_platform_without_reload_or_unknown_entries():
    assert package(None, "alarm_control_panel:\n  - platform: manual\n").reasons == [
        "packages/p.yaml: alarm_control_panel (manual) can't be reloaded"]
    assert package(None, "sensor: !include sensors.yaml\n").reasons == ["packages/p.yaml: sensor can't be reloaded"]
    assert package(None, "light:\n  - name: no platform\n").needed


def test_only_changed_sections_count():
    old = "powercalc:\n  a: 1\nautomation:\n  - alias: a\n"
    new = "powercalc:\n  a: 1\nautomation:\n  - alias: b\n"
    assert not package(old, new).needed
    assert package(old, new.replace("a: 1", "a: 2")).needed


def test_unparseable_package_needs_restart():
    assert package(None, "automation: [broken\n").reasons == ["packages/p.yaml couldn't be read as a package"]
    assert package(None, "- not a mapping\n").needed


def test_reload_only_dirs_editor_files_and_dotfiles():
    v = needs_restart(["dashboards/home.yaml", "themes/t.yaml", "blueprints/a/b.yaml", "www/x.js",
                       "automations.yaml", "scripts.yaml", "scenes.yaml", "README.md", "docs/a.md",
                       ".pre-commit-config.yaml", ".github/workflows/ci.yaml", ".ci/x.yaml"],
                      contents({}))
    assert not v.needed


def test_other_yaml_is_unknown_and_needs_restart():
    v = needs_restart(["sensors.yaml"], contents({}))
    assert v.needed and "may be included" in v.reasons[0]


def test_extra_globs_and_custom_packages_dir():
    v = needs_restart(["www/app/module.js"], contents({}), extra_globs=["www/**/*.js", " "])
    assert v.needed and v.reasons == ["www/app/module.js matches a restart rule"]
    v = needs_restart(["pkg/a.yaml"], contents({"pkg/a.yaml": (None, "script:\n  s: {}\n")}),
                      packages_dir="pkg/")
    assert not v.needed


def test_reload_globs_mark_files_never_loaded():
    v = needs_restart(["secrets.fake.yaml", "sensors.yaml"], contents({}), reload_globs=["secrets.fake.yaml"])
    assert v.reasons == ["sensors.yaml may be included by configuration.yaml"]
    # Restart rules and configuration.yaml still win.
    v = needs_restart(["configuration.yaml"], contents({}), reload_globs=["*.yaml"])
    assert v.needed
