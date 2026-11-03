from custom_components.git_config_updater.core.restart import needs_restart, top_level_keys


def contents(table):
    return lambda p: table.get(p, (None, None))


def test_top_level_keys():
    text = "# comment\ninput_boolean:\n  a:\n    name: A\ntemplate: !include t.yaml\n- not: a key\n  nested: x\n"
    assert top_level_keys(text) == {"input_boolean", "template"}
    assert top_level_keys(None) == set()


def test_configuration_and_custom_components_need_restart():
    v = needs_restart(["configuration.yaml", "custom_components/foo/sensor.py"], contents({}))
    assert v.needed
    assert "configuration.yaml changed" in v.reasons
    assert "custom integration changed (foo)" in v.reasons


def test_reloadable_package():
    v = needs_restart(["packages/lights.yaml"], contents({
        "packages/lights.yaml": ("input_boolean:\n  a: {}\n", "input_boolean:\n  a: {}\nscript:\n  b: {}\n")}))
    assert not v.needed


def test_package_with_non_reloadable_domain():
    v = needs_restart(["packages/energy.yaml"], contents({
        "packages/energy.yaml": (None, "sensor:\n  - platform: statistics\ncounter:\n  c: {}\n")}))
    assert v.needed
    assert v.reasons == ["packages/energy.yaml: counter, sensor can't be reloaded"]


def test_removed_non_reloadable_domain_also_counts():
    v = needs_restart(["packages/x.yaml"], contents({"packages/x.yaml": ("powercalc:\n  a: 1\n", None)}))
    assert v.needed


def test_reload_only_dirs_and_editor_files():
    v = needs_restart(["dashboards/home.yaml", "themes/t.yaml", "blueprints/a/b.yaml", "www/x.js",
                       "automations.yaml", "scripts.yaml", "scenes.yaml", "README.md", "docs/a.md"],
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
