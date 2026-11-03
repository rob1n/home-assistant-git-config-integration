"""Constants for Git Config Updater."""
from __future__ import annotations

DOMAIN = "git_config_updater"

CONF_NAME = "name"
CONF_REPOSITORY = "repository"
CONF_BRANCH = "branch"
CONF_TOKEN = "token"
CONF_PATH = "path"

OPT_SCAN_MINUTES = "scan_interval"
OPT_BACKUP = "backup"
OPT_RESTART_GLOBS = "restart_globs"
OPT_RELOAD_GLOBS = "reload_globs"
OPT_PACKAGES_DIR = "packages_dir"
OPT_REQUIRE_CI = "require_ci"

DEFAULT_NAME = "Home Assistant config"
DEFAULT_BRANCH = "main"
DEFAULT_SCAN_MINUTES = 5
DEFAULT_PACKAGES_DIR = "packages"

GITHUB_API = "https://api.github.com"
GITHUB_WEB = "https://github.com"

ISSUE_RESTART = "restart_required"
