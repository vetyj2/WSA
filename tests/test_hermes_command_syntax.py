import json
import re
import shlex
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase
from unittest.mock import patch

from wsa.cli import main
from wsa.hermes_commands import build_hermes_command_registry
from wsa.workspace import create_world


PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]+))?\}")
TELEGRAM_COMMAND_RE = re.compile(r"^/[a-z0-9_]{1,32}$")


def normalize_alias(value: str) -> str:
    lowered = value.strip().lower()
    if lowered.startswith("/"):
        return lowered.replace("-", "_")
    return " ".join(lowered.split())


def iter_string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_string_values(item)


def parse_hermes_text(text: str, registry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    tokens = shlex.split(text)
    alias_map = {}
    for command in registry["commands"]:
        for alias in [command["command"], *command.get("aliases", [])]:
            alias_map[normalize_alias(alias)] = command
    command = alias_map[normalize_alias(tokens[0])]
    args: dict[str, Any] = {}
    repeatable = {
        item["name"]
        for item in command.get("arguments", [])
        if item.get("repeatable") is True
    }
    for token in tokens[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key in repeatable:
            args.setdefault(key, []).append(value)
        else:
            args[key] = value
    return command, args


def render_token(template: str, args: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        value = args.get(name, default)
        if isinstance(value, list):
            return " ".join(value)
        if value is None:
            raise KeyError(f"missing placeholder: {name}")
        return str(value)

    return PLACEHOLDER_RE.sub(replace, template)


def render_template(template: list[str], args: dict[str, Any]) -> list[str]:
    return [render_token(item, args) for item in template]


def render_input_json(template: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    rendered: dict[str, Any] = {}
    for key, value in template.items():
        if isinstance(value, str):
            try:
                rendered_value = render_token(value, args)
            except KeyError:
                continue
            if PLACEHOLDER_RE.fullmatch(value) and rendered_value == "":
                continue
            rendered[key] = rendered_value
        else:
            rendered[key] = value
    return rendered


class HermesCommandSyntaxTests(TestCase):
    def test_registry_declares_portable_argv_and_path_policy(self) -> None:
        registry = build_hermes_command_registry()

        self.assertTrue(registry["cli_template_policy"]["argv_array_required"])
        self.assertEqual(registry["cli_template_policy"]["shell_joining"], "forbidden_by_default")
        self.assertEqual(registry["cli_template_policy"]["optional_unset_policy"], "omit_flag_and_value_or_omit_input_json_key")
        self.assertEqual(registry["runtime_portability"]["cwd_policy"], "workspace_root_recommended")
        self.assertEqual(registry["runtime_portability"]["workspace_env"], "WSA_WORKSPACE")
        reporting = registry["reporting_artifact_policy"]
        self.assertEqual(reporting["schema"], "wsa.reporting.artifact_contract.v1")
        self.assertFalse(reporting["storage_policy"]["store_every_export_by_default"])
        self.assertTrue(reporting["storage_policy"]["session_log_is_source_of_truth"])
        self.assertIn(
            "worlds/{world_id}/artifacts/",
            reporting["storage_policy"]["managed_artifact_roots"],
        )
        self.assertTrue(
            reporting["storage_policy"]["out_of_contract_artifact_policy"]["source_map_required"]
        )
        self.assertEqual(
            [item["artifact_type"] for item in reporting["recommended_exports"]],
            [
                "human_session_minutes",
                "draft_output",
                "round_orchestration_report",
            ],
        )
        self.assertIn(
            "fact_audit_evidence_count",
            reporting["actor_contribution_accounting"]["recommended_counts"],
        )
        self.assertIn(
            "line_build_ledger_entry_count",
            reporting["actor_contribution_accounting"]["recommended_counts"],
        )
        self.assertIn("scene_mode_evidence_contracts", reporting)
        self.assertIn(
            "source_refs",
            reporting["scene_mode_evidence_contracts"]["fact_audit_synthesis"][
                "required_to_claim_deep_fact_audit"
            ][0],
        )

    def test_canonical_commands_are_telegram_menu_safe_and_aliases_do_not_cross_collide(self) -> None:
        registry = build_hermes_command_registry()
        seen: dict[str, str] = {}

        for command in registry["commands"]:
            canonical = command["command"]
            self.assertRegex(canonical, TELEGRAM_COMMAND_RE)
            self.assertIn("cli_template_policy", command)
            for alias in [canonical, *command.get("aliases", [])]:
                normalized = normalize_alias(alias)
                if normalized in seen:
                    self.assertEqual(seen[normalized], canonical)
                else:
                    seen[normalized] = canonical

        self.assertEqual(seen["/filltherest_start"], "/filltherest_start")
        self.assertEqual(seen["/filltherest_plan"], "/filltherest_plan")

    def test_all_template_placeholders_are_declared_arguments(self) -> None:
        registry = build_hermes_command_registry()

        for command in registry["commands"]:
            argument_names = {item["name"] for item in command.get("arguments", [])}
            strings = list(iter_string_values(command.get("cli_templates", [])))
            strings.extend(iter_string_values(command.get("input_json_template", {})))
            for value in strings:
                for match in PLACEHOLDER_RE.finditer(value):
                    self.assertIn(
                        match.group(1),
                        argument_names,
                        f"{command['command']} has undeclared placeholder {match.group(0)}",
                    )

    def test_representative_hermes_syntax_aliases_parse_to_expected_commands(self) -> None:
        registry = build_hermes_command_registry()
        cases = {
            '/wsa-easystartup world_id=wld_demo budget=8': "/wsa_easystartup",
            '/wsa_pick world_id=wld_demo text="0001f 0002b plus notes"': "/wsa_pick",
            '/filltherest-start world_id=wld_demo destination="until 3 regions exist" cron_schedule="daily"': "/filltherest_start",
            '/filltherest-plan world_id=wld_demo destination="until 3 regions exist"': "/filltherest_plan",
            '/wsa-meeting world_id=wld_demo topic="Succession gap" participant="Council" participant="Guild"': "/wsa_meeting",
            '/wsa-meetup world_id=wld_demo topic="rival institutions" participant="North" participant="South"': "/wsa_orchestrator",
            '/wsa-scene-start world_id=wld_demo topic="station opening" participant="Narrator"': "/wsa_scene_start",
        }

        for text, expected in cases.items():
            command, args = parse_hermes_text(text, registry)
            self.assertEqual(command["command"], expected)
            self.assertIn("world_id", args)

    def test_hermes_style_commands_render_to_cli_without_shell_quoting(self) -> None:
        registry = build_hermes_command_registry()
        commands = {item["command"]: item for item in registry["commands"]}

        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Syntax World")

            pick_args = {
                "world_id": world.world_id,
                "text": "0001f 0002b 그리고 따옴표 \"있는\" 답변도 안전하게",
            }
            pick_template = commands["/wsa_pick"]["cli_templates"][1]
            pick_argv = render_template(pick_template, pick_args)
            self.assertEqual(pick_argv[0], "wsa")
            pick_stdout = StringIO()
            with patch("sys.stdout", pick_stdout):
                pick_code = main(["--workspace", str(workspace), *pick_argv[1:]])
            pick_payload = json.loads(pick_stdout.getvalue())

            start_args = {
                "world_id": world.world_id,
                "destination": "until the trade district has factions, conflicts,\nand scene hooks",
                "scope": "trade district",
                "discretion_level": 5,
                "cron_schedule": "daily",
                "quality_bar": "no duplicate filler",
            }
            start_template = commands["/filltherest_start"]["cli_templates"][0]
            start_argv = render_template(start_template, start_args)
            start_payload = render_input_json(
                commands["/filltherest_start"]["input_json_template"],
                start_args,
            )
            start_stdout = StringIO()
            with patch("sys.stdout", start_stdout):
                start_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        *start_argv[1:],
                        "--input-json",
                        json.dumps(start_payload, ensure_ascii=False),
                    ]
                )

            self.assertEqual(pick_code, 0)
            self.assertEqual(pick_payload["status"]["active_mode"], "easystartup")
            self.assertEqual(start_code, 0)
            self.assertIn("hermes_task_created:", start_stdout.getvalue())
