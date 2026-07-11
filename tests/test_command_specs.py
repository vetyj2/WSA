from unittest import TestCase

from wsa.cli import build_parser
from wsa.command_specs import PUBLIC_COMMAND_SPECS, canonical_menu_surface
from wsa.hermes_commands import build_hermes_command_registry


class CommandSpecTests(TestCase):
    def test_public_command_specs_match_parser_and_hermes_menu(self) -> None:
        parser = build_parser()
        registry = build_hermes_command_registry()
        menu = canonical_menu_surface()
        commands = {item["command"] for item in registry["commands"]}

        self.assertEqual(len(menu["entries"]), len(PUBLIC_COMMAND_SPECS))
        for spec, entry in zip(PUBLIC_COMMAND_SPECS, menu["entries"]):
            parsed = parser.parse_args(list(spec.parser_smoke_argv))
            self.assertIsNotNone(parsed.command)
            self.assertEqual(entry["label"], spec.label)
            self.assertEqual(entry["current_routes"], list(spec.current_routes))
            if spec.primary_command is not None:
                self.assertIn(spec.primary_command, commands)

    def test_compact_registry_keeps_cli_templates_but_removes_expanded_contracts(self) -> None:
        full = build_hermes_command_registry()
        compact = build_hermes_command_registry(compact=True)

        self.assertLess(len(str(compact)), len(str(full)))
        self.assertEqual(
            [item["command"] for item in compact["commands"]],
            [item["command"] for item in full["commands"]],
        )
        self.assertTrue(
            any("runtime_contract_ref" in item for item in compact["commands"])
        )
        self.assertTrue(
            all("runtime_contract" not in item for item in compact["commands"])
        )
