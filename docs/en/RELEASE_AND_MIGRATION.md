# Release and Migration

WSA 0.3.1 is a schema-compatible SOL refactor patch on top of 0.3.0. Control and world databases remain schema v2; Startup profiles and workflow run projections have separate version markers, so do not assume package and data versions are identical.

Before migration, stop Hermes task intake, callbacks, and scheduled work. Run `wsa update preflight` and read-only `wsa migrate --format json`, then execute `wsa migrate --apply --format json`. Preserve the reported backup path and verify with Doctor, Manager diagnostics, and world inspection before resuming the external runtime.

Only ordered v1 -> v2 upgrade is supported. Automatic downgrade is not. A failed migration reports the `.wsa_migration_backups/<timestamp>/` recovery source. Rerunning after a partial upgrade skips stores already at the current version.

## 0.3.1 SOL Refactor

- Adds the guided `ticket next -> review-next -> apply-next` flow.
- Adds atomic amend/split/merge lineage and deep actor lifecycle replacement.
- Verifies 278 tests, strict warnings, Ruff, mypy, build/install, public-tree, and fresh-clone smoke.

Version 0.3.0 adds neutral Startup v2; candidate materialization, non-mutating ticket review, and concrete/idempotent application; world proposal and inspection paths; viewpoint-safe context assembly; SQLite RunStore revisions and callback receipts; explicit migration and projection repair; compact contract projections; severity-aware pure diagnostics with separate record and repair actions; compatibility facades with sub-800-line CLI, Hermes registry, and repository modules; a unified `wsa.artifacts` operation package; public CI; and an installed golden-path smoke test. `ticket approve` remains an alias for `ticket apply`, and direct application of existing proposed concrete tickets remains supported; new workflows should use `ticket review -> ticket apply`.
