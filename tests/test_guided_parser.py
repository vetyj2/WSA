from unittest import TestCase

from wsa.cli_parser import build_parser


class GuidedParserTests(TestCase):
    def test_guided_authoring_and_runtime_examples_parse(self) -> None:
        parser = build_parser()
        examples = [
            [
                "ticket",
                "compose",
                "--world",
                "World Name",
                "--add-entity",
                "character|Mina",
                "--add-fact",
                "Mina|role|navigator",
                "--write-ticket",
            ],
            [
                "ticket",
                "compose",
                "--accept-candidate",
                "ticket-1",
                "--skip-index",
                "2",
                "--add-fact",
                "Mina|mood|focused",
            ],
            [
                "ticket",
                "amend",
                "ticket-1",
                "--skip-index",
                "1",
                "--add-fact",
                "Mina|role|pilot",
            ],
            ["ticket", "next", "--world", "World Name"],
            ["ticket", "review-next"],
            ["ticket", "apply-next", "--format", "json"],
            [
                "ticket",
                "split",
                "ticket-1",
                "--part",
                "1,3",
                "--part",
                "2",
            ],
            [
                "ticket",
                "merge",
                "ticket-1",
                "ticket-2",
                "--title",
                "Combined",
            ],
            [
                "world",
                "actor",
                "attribute",
                "world-1",
                "Mina",
                "--dimension",
                "condition",
                "--value-text",
                "wounded",
                "--valid-from",
                "002",
            ],
            [
                "world",
                "actor",
                "knowledge",
                "world-1",
                "Mina",
                "--target-type",
                "fact",
                "--target-id",
                "fact-1",
                "--state",
                "known",
            ],
            [
                "world",
                "actor",
                "profile",
                "world-1",
                "Mina",
                "--fragment",
                "goal",
                "--text",
                "Reach the tower",
                "--replace-record",
                "profile-1",
                "--replace-at",
                "005",
            ],
            [
                "world",
                "actor",
                "revise",
                "world-1",
                "Mina",
                "--record-type",
                "actor_profile",
                "--record-id",
                "profile-1",
                "--status",
                "deprecated",
            ],
            [
                "world",
                "fork-plan",
                "world-1",
                "--name",
                "Alternative",
                "--entity",
                "entity-1",
                "--format",
                "json",
            ],
            [
                "orchestrator",
                "dispatch",
                "run-1",
                "--workdir",
                "/tmp",
                "--confirm",
                "--runtime-command",
                "python3",
                "adapter.py",
                "--adapter-option",
            ],
        ]

        for argv in examples:
            with self.subTest(argv=argv):
                parsed = parser.parse_args(argv)
                self.assertIsNotNone(parsed.command)

        runtime = parser.parse_args(examples[-1])
        self.assertEqual(
            runtime.runtime_argv,
            ["python3", "adapter.py", "--adapter-option"],
        )
