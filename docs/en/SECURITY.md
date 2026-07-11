# Security Policy

Security fixes target `main` and the latest release line. Do not post keys, tokens, private paths, or callback contents in public issues. Prefer [GitHub private security advisories](https://github.com/vetyj2/WSA/security/advisories/new).

WSA does not own provider credentials, OAuth tokens, SSH keys, or a long-running Hermes process. External runtimes own agents and provider permissions; WSA manages bounded hooks, structural callback validation, reports, tickets, and local state. After the user supplies and confirms argv/workdir, the stdio adapter may run one external command, but it does not discover a provider or credentials.

Callback validation is schema- and route-based, not cryptographic authentication. Never expose `workspace/hermes/callbacks/` as an untrusted upload endpoint. World mutation remains behind concrete ticket application, callback replay is recorded in SQLite, and schema migration requires plan, backup, apply, and verification.

Stdio dispatch requires `--confirm`, uses `shell=False`, a minimal environment allowlist, bounded I/O, and a timeout. Runtime commands and credentials belong in the user's local boundary, not the public command registry.

Report the affected WSA/Python versions, attacker-controlled input, minimal reproduction, redacted evidence, and concrete impact. See the Korean root [SECURITY.md](../../SECURITY.md) for the primary policy.
