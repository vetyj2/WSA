from __future__ import annotations


HERMES_COMMAND_REGISTRY_SCHEMA = "wsa.hermes.command_registry.v1"
HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA = "wsa.hermes.command_registry.local.v1"
HERMES_COMMAND_OVERLAY_REPORT_SCHEMA = "wsa.hermes.command_overlay_report.v1"
HERMES_COMMAND_REGISTRY_FILENAME = "hermes_commands.example.json"
HERMES_LOCAL_COMMAND_REGISTRY_FILENAME = "hermes_commands.local.json"
LOCAL_COMMAND_RESERVED_PREFIXES = ("/wsa_", "/filltherest", "/fill_the_rest", "/fillrest")
LOCAL_COMMAND_MUTATING_SAFETIES = {"requires_approval", "workspace_mutating", "world_mutating"}
KNOWN_COMMAND_SAFETIES = {
    "proposal_only",
    "read_only",
    "requires_approval",
    "workspace_mutating",
    "world_mutating",
}
