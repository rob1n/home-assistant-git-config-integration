# Git Config Updater

Install changes to a git-managed Home Assistant configuration from the Home Assistant UI.

If your configuration folder is a git checkout of a GitHub repository, this integration shows that
repository as an update in **Settings → Updates**. When new commits land on the branch, you see what
changed and click **Install**: it pulls them, checks the configuration, and reloads. No SSH, no
deploy script.

## What it does

- **Checks** the branch every few minutes (configurable), and when you press **Check for updates**.
- **Shows a changelog** before you install: the new commits, the CI result of the latest one, the
  changed files, and whether a restart will be needed. A link opens the full diff on GitHub.
- **Installs safely**, in this order:
  1. Refuses if tracked files in the checkout have local changes (it lists them), so nothing edited
     on the host is overwritten. A local edit that equals the new version doesn't count.
  2. Optionally creates a backup first (Home Assistant only, without the database).
  3. Fetches the branch over HTTPS. The token is passed per command and never written to
     `.git/config`; the checkout's own `origin` remote is left alone.
  4. Fast-forwards the checkout, and refuses if that isn't possible (the checkout has its own commits).
  5. Checks the configuration. If it's invalid, the checkout is reset to the previous commit and the
     errors are shown.
  6. Touches the YAML dashboards (so they're re-read) and runs `homeassistant.reload_all`.
  7. If a reload isn't enough, raises a **Restart needed** repair with a button to restart. It never
     restarts on its own.

### When is a restart needed?

The rule is conservative: anything not known to be reloadable needs a restart.

- `configuration.yaml`, and anything under `custom_components/`: restart.
- Package files (YAML in the packages directory, `packages/` by default): reload, if every top-level
  key before and after the change is a reloadable domain (automation, script, scene, template, group,
  timer, schedule, person, zone, the `input_*` helpers, …). Otherwise restart.
- `automations.yaml`, `scripts.yaml`, `scenes.yaml`, and files in `dashboards/`, `themes/`,
  `blueprints/`, `www/` and similar folders, and non-YAML files: reload.
- Any other YAML file could be included by `configuration.yaml` for any integration: restart.
- You can add your own restart rules (globs) in the options, e.g. `www/**/*.js` for frontend modules
  loaded through `extra_module_url`.

## Requirements

- Home Assistant 2026.10 or newer, with `git` available (it is in the official container images,
  including Home Assistant OS).
- The configuration folder is a git checkout of a GitHub repository.
- A GitHub [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new):
  - Repository access: only the configuration repository.
  - Permissions: **Contents: Read-only** (required). **Commit statuses** and **Checks: Read-only**
    are optional; without them the CI result shows as "unknown".

## Installation

From 2026.11, add this repository in **Settings → Marketplace** as a custom repository (category
Integration) and install it. On 2026.10 with HACS: **HACS → ⋮ → Custom repositories**, add
`https://github.com/rob1n/home-assistant-git-config-integration` with category Integration, install,
and restart Home Assistant.

Then **Settings → Devices & services → Add integration → Git Config Updater**:

| Field | Example | Notes |
|---|---|---|
| Name | Home Assistant config | Becomes the update entity's name. |
| GitHub repository | `your-user/ha-config` | `owner/name`. |
| Branch | `main` | The branch to deploy from. |
| GitHub token | | Fine-grained, see above. Stored in the config entry only. |
| Checkout path | `/config` | Defaults to the Home Assistant config folder. |

Options (**Configure** on the integration): check interval, backup before installing, packages
directory, extra restart rules.

When the token expires, Home Assistant asks for a new one (a reauthentication).

## Recovery

The integration runs inside Home Assistant. If a change stops Home Assistant from starting, it can't
help: fix the checkout from a shell (for example the Terminal & SSH app), e.g.
`git -C /config reset --hard <previous commit>`, and restart. Invalid configuration caught by the check
in step 5 never gets that far.

## Development

```sh
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/ruff check custom_components tests
.venv/bin/pytest
```

The pure logic (git commands, restart rules, CI status, changelog) is in
`custom_components/git_config_updater/core/` and has no Home Assistant imports. The tests run git
against temporary local repositories.

## License

MIT
