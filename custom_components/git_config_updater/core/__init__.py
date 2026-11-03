"""Pure logic of Git Config Updater: no Home Assistant imports, so it can be tested with plain
pytest. `gitops` wraps the git binary, `restart` decides whether a change needs a restart, `ci`
folds GitHub check runs into one status and `changelog` renders the release notes."""
