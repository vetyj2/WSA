import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.application.deep_authoring_service import (
    DeepAuthoringService,
    actor_memory_change,
    actor_profile_change,
    knowledge_attribution_change,
    temporal_attribute_change,
)
from wsa.cli import main
from wsa.context import ContextBuilder
from wsa.repositories import WorldRepository
from wsa.tickets import UnsupportedTicketChangeError, apply_ticket, review_ticket
from wsa.workspace import create_world, sqlite_connection, world_db_path


class DeepAuthoringTests(TestCase):
    def test_actor_cli_previews_and_applies_without_authored_json(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Actor CLI World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mina")

            preview_output = StringIO()
            with redirect_stdout(preview_output):
                preview_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "actor",
                        "profile",
                        world.world_id,
                        "Mina",
                        "--fragment",
                        "goal",
                        "--text",
                        "Reach the signal tower.",
                    ]
                )
            self.assertEqual(preview_code, 0)
            self.assertIn("read_only_preview_no_world_mutation", preview_output.getvalue())
            self.assertEqual(repo.list_actor_profiles(actor.entity_id), [])

            write_output = StringIO()
            with redirect_stdout(write_output):
                write_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "actor",
                        "profile",
                        world.world_id,
                        "Mina",
                        "--fragment",
                        "goal",
                        "--text",
                        "Reach the signal tower.",
                        "--write-ticket",
                    ]
                )
            self.assertEqual(write_code, 0)
            ticket_id = next(
                line.split(": ", 1)[1]
                for line in write_output.getvalue().splitlines()
                if line.startswith("ticket_id: ")
            )
            self.assertEqual(repo.list_actor_profiles(actor.entity_id), [])

            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "review",
                            world.world_id,
                            ticket_id,
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "apply",
                            world.world_id,
                            ticket_id,
                        ]
                    ),
                    0,
                )

            show_output = StringIO()
            with redirect_stdout(show_output):
                show_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "actor",
                        "show",
                        world.world_id,
                        "Mina",
                        "--format",
                        "json",
                    ]
                )
            payload = json.loads(show_output.getvalue())
            self.assertEqual(show_code, 0)
            self.assertEqual(payload["profiles"][0]["fragment_type"], "goal")

    def test_preview_review_and_apply_typed_authoring_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Deep Authoring World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mina")
            hidden_fact = repo.create_fact(
                world.world_id,
                "sealed_truth",
                "the harbor signal is forged",
                authority="canon",
                status="canon",
                payload={"visibility": "hidden"},
            )
            service = DeepAuthoringService(repo)
            source_ref = "author-session:phase3"
            changes = [
                actor_profile_change(
                    actor.entity_id,
                    "core_profile",
                    {"summary": "A cautious harbor pilot."},
                    source_ref=source_ref,
                ),
                temporal_attribute_change(
                    actor.entity_id,
                    "condition",
                    value_text="ready",
                    valid_from="001",
                    valid_until="003",
                    source_ref=source_ref,
                ),
                knowledge_attribution_change(
                    actor.entity_id,
                    "fact",
                    hidden_fact.fact_id,
                    "known",
                    acquired_at="001",
                    source_ref=source_ref,
                ),
                actor_memory_change(
                    actor.entity_id,
                    "001",
                    {"summary": "Saw the first signal."},
                    source_ref=source_ref,
                ),
            ]

            preview = service.preview(
                "Establish Mina's initial state",
                changes,
                source_ref=source_ref,
            )

            self.assertEqual(preview.to_dict()["change_count"], 4)
            self.assertEqual(repo.list_actor_profiles(actor.entity_id), [])
            self.assertEqual(repo.query_entity_attribute_spans(actor.entity_id), [])
            self.assertEqual(repo.query_knowledge_attributions(actor.entity_id), [])
            self.assertEqual(repo.list_actor_memory_packets(actor.entity_id), [])

            ticket = service.write_ticket(preview)
            self.assertEqual(ticket.status, "proposed")
            self.assertEqual(repo.list_actor_profiles(actor.entity_id), [])

            reviewed = review_ticket(repo, ticket.ticket_id)
            self.assertEqual(reviewed.status, "approved")
            self.assertEqual(repo.list_actor_profiles(actor.entity_id), [])

            applied = apply_ticket(repo, ticket.ticket_id)
            self.assertEqual(applied.status, "applied")
            self.assertEqual(len(applied.applied_ids), 5)
            profile = repo.list_actor_profiles(actor.entity_id)[0]
            span = repo.query_entity_attribute_spans(actor.entity_id)[0]
            knowledge = repo.query_knowledge_attributions(actor.entity_id)[0]
            memory = repo.list_actor_memory_packets(actor.entity_id)[0]
            self.assertEqual(profile.fragment_type, "core")
            self.assertEqual(profile.payload["_wsa"]["source_ref"], source_ref)
            self.assertEqual(span.valid_from, "001")
            self.assertEqual(span.valid_until, "003")
            self.assertEqual(span.payload["_wsa"]["authority"], "user_explicit")
            self.assertEqual(knowledge.acquired_at, "001")
            self.assertEqual(knowledge.payload["_wsa"]["source_ref"], source_ref)
            self.assertEqual(memory.time_scope, "001")
            self.assertEqual(memory.payload["_wsa"]["source_ref"], source_ref)

    def test_time_specific_context_and_secret_viewpoint_filtering(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Temporal Actor World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ren")
            viewer = repo.create_entity("character", "Sol")
            service = DeepAuthoringService(repo)
            source_ref = "author-session:temporal"
            changes = [
                actor_profile_change(
                    actor.entity_id,
                    "secret",
                    {"summary": "Ren sent the forbidden signal."},
                    valid_from="002",
                    source_ref=source_ref,
                ),
                temporal_attribute_change(
                    actor.entity_id,
                    "condition",
                    value_text="calm",
                    valid_from="001",
                    valid_until="002",
                    source_ref=source_ref,
                ),
                temporal_attribute_change(
                    actor.entity_id,
                    "condition",
                    value_text="wounded",
                    valid_from="002",
                    source_ref=source_ref,
                ),
                actor_memory_change(
                    actor.entity_id,
                    "001",
                    {"summary": "Entered the harbor."},
                    source_ref=source_ref,
                ),
                actor_memory_change(
                    actor.entity_id,
                    "002",
                    {"summary": "Heard the shot."},
                    source_ref=source_ref,
                ),
            ]
            self._write_review_apply(
                service,
                "Build Ren's temporal context",
                changes,
                source_ref,
            )

            before = ContextBuilder(repo).build_actor_context(
                actor,
                "scene-001",
                "enter harbor",
                time_scope="001",
                persist=False,
            )
            after = ContextBuilder(repo).build_actor_context(
                actor,
                "scene-002",
                "respond to shot",
                time_scope="002",
                persist=False,
            )
            outsider = ContextBuilder(repo).build_actor_context(
                actor,
                "scene-002",
                "observe Ren",
                time_scope="002",
                viewpoint_entity_id=viewer.entity_id,
                persist=False,
            )

            self.assertEqual(before["temporal_attributes"][0]["value_text"], "calm")
            self.assertEqual(after["temporal_attributes"][0]["value_text"], "wounded")
            self.assertEqual(len(before["memories"]), 1)
            self.assertEqual(len(after["memories"]), 2)
            self.assertEqual(before["actor_profiles"], [])
            self.assertEqual(after["actor_profiles"][0]["fragment_type"], "secret")
            self.assertEqual(outsider["actor_profiles"], [])

            secret_profile_id = repo.list_actor_profiles(actor.entity_id)[0].actor_profile_id
            self._write_review_apply(
                service,
                "Let Sol discover Ren's secret",
                [
                    knowledge_attribution_change(
                        viewer.entity_id,
                        "actor_profile",
                        secret_profile_id,
                        "discovered",
                        acquired_at="002",
                        source_ref=source_ref,
                    )
                ],
                source_ref,
            )
            informed = ContextBuilder(repo).build_actor_context(
                actor,
                "scene-002",
                "confront Ren",
                time_scope="002",
                viewpoint_entity_id=viewer.entity_id,
                persist=False,
            )
            self.assertEqual(informed["actor_profiles"][0]["fragment_type"], "secret")

    def test_hidden_fact_requires_known_and_forbidden_state_wins_by_time(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Forbidden Knowledge World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mira")
            hidden_fact = repo.create_fact(
                world.world_id,
                "hidden_route",
                "under the old bridge",
                authority="canon",
                status="canon",
                payload={"visibility": "hidden"},
            )
            service = DeepAuthoringService(repo)
            source_ref = "author-session:knowledge"
            builder = ContextBuilder(repo)

            unknown = builder.build_actor_context(
                actor,
                "scene-001",
                "find route",
                time_scope="001",
                persist=False,
            )
            self.assertEqual(unknown["facts"], [])

            self._write_review_apply(
                service,
                "Mira learns the route",
                [
                    knowledge_attribution_change(
                        actor.entity_id,
                        "fact",
                        hidden_fact.fact_id,
                        "known",
                        acquired_at="002",
                        source_ref=source_ref,
                    )
                ],
                source_ref,
            )
            self._write_review_apply(
                service,
                "Temporarily forbid route knowledge",
                [
                    knowledge_attribution_change(
                        actor.entity_id,
                        "fact",
                        hidden_fact.fact_id,
                        "forbidden",
                        acquired_at="003",
                        valid_until="004",
                        source_ref=source_ref,
                    )
                ],
                source_ref,
            )

            known = builder.build_actor_context(
                actor,
                "scene-002",
                "use route",
                time_scope="002",
                persist=False,
            )
            forbidden = builder.build_actor_context(
                actor,
                "scene-003",
                "use route",
                time_scope="003",
                persist=False,
            )
            restored = builder.build_actor_context(
                actor,
                "scene-004",
                "use route",
                time_scope="004",
                persist=False,
            )
            self.assertEqual(known["facts"][0]["fact_id"], hidden_fact.fact_id)
            self.assertEqual(forbidden["facts"], [])
            self.assertIn(
                "forbidden_to_viewpoint",
                {item["reason"] for item in forbidden["receipt"]["excluded"]},
            )
            self.assertEqual(restored["facts"][0]["fact_id"], hidden_fact.fact_id)

    def test_invalid_references_and_failed_apply_leave_no_partial_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Atomic Authoring World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ira")
            service = DeepAuthoringService(repo)
            source_ref = "author-session:rollback"

            with self.assertRaises(KeyError):
                service.preview(
                    "Invalid actor reference",
                    [
                        actor_profile_change(
                            "entity_missing",
                            "goal",
                            {"summary": "Escape."},
                            source_ref=source_ref,
                        )
                    ],
                    source_ref=source_ref,
                )
            with self.assertRaises(UnsupportedTicketChangeError):
                service.preview(
                    "Conflicting dimension types",
                    [
                        temporal_attribute_change(
                            actor.entity_id,
                            "condition",
                            value_text="ready",
                            source_ref=source_ref,
                        ),
                        temporal_attribute_change(
                            actor.entity_id,
                            "condition",
                            value_number=2,
                            source_ref=source_ref,
                        ),
                    ],
                    source_ref=source_ref,
                )
            self.assertEqual(repo.list_tickets(), [])

            preview = service.preview(
                "Atomic actor update",
                [
                    actor_profile_change(
                        actor.entity_id,
                        "goal",
                        {"summary": "Reach the tower."},
                        source_ref=source_ref,
                    ),
                    actor_memory_change(
                        actor.entity_id,
                        "001",
                        {"summary": "Found the map."},
                        source_ref=source_ref,
                    ),
                ],
                source_ref=source_ref,
            )
            ticket = service.write_ticket(preview)
            review_ticket(repo, ticket.ticket_id)
            with sqlite_connection(world_db_path(world.path)) as conn:
                conn.execute(
                    """
                    CREATE TRIGGER reject_phase3_memory
                    BEFORE INSERT ON actor_memory_packets
                    BEGIN
                        SELECT RAISE(ABORT, 'forced memory rejection');
                    END
                    """
                )
                conn.commit()

            with self.assertRaises(IntegrityError):
                apply_ticket(repo, ticket.ticket_id)

            self.assertEqual(repo.list_actor_profiles(actor.entity_id), [])
            self.assertEqual(repo.list_actor_memory_packets(actor.entity_id), [])
            self.assertEqual(repo.get_ticket(ticket.ticket_id).status, "approved")

    def _write_review_apply(
        self,
        service: DeepAuthoringService,
        title: str,
        changes: list[dict],
        source_ref: str,
    ) -> None:
        preview = service.preview(title, changes, source_ref=source_ref)
        ticket = service.write_ticket(preview)
        review_ticket(service.repo, ticket.ticket_id)
        apply_ticket(service.repo, ticket.ticket_id)
