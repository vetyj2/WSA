# Contributing

Use Python 3.9 or newer:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
```

Preserve WSA's boundaries: no credential or process ownership, explicit proposal/callback/canon provenance, preview -> ticket -> apply for world mutation, explicit schema migration, and public examples without live secrets or private paths.

Run the strict unit suite, compile check, public-tree scan, and documentation parity check described in the root [CONTRIBUTING.md](../../CONTRIBUTING.md). CLI or Hermes route changes must update `command_specs.py` and its drift tests. Schema changes require ordered migrations and old-fixture preservation tests.
