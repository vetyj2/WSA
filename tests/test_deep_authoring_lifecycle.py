from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.application.deep_authoring_service import (
    DeepAuthoringService,
    actor_profile_change,
    deep_record_replacement_changes,
    lifecycle_revision_change,
)
from wsa.context import ContextBuilder
from wsa.repositories import WorldRepository
from wsa.tickets import (
    UnsupportedTicketChangeError,
    apply_ticket,
    review_ticket,
)
from wsa.workspace import create_world, sqlite_connection, utc_now, world_db_path


class DeepAuthoringLifecycleTests(TestCase):
    def test_preview_review_and_apply_deprecation_preserve_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Lifecycle Preview World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mina")
            original_payload = {
                "summary": "Keep the harbor open.",
                "custom": {"keep": True},
                "_wsa": {
                    "source_ref": "seed:profile",
                    "authority": "canon",
                    "valid_from": "001",
                    "valid_until": None,
                },
            }
            profile = repo.create_actor_profile(
                actor.entity_id,
                "goal",
                original_payload,
                status="active",
            )
            service = DeepAuthoringService(repo)

            with self.assertRaises(ValueError):
                lifecycle_revision_change(
                    "actor_profile",
                    profile.actor_profile_id,
                    source_ref="revision:empty",
                )
            with self.assertRaises(UnsupportedTicketChangeError):
                service.preview(
                    "No-op profile revision",
                    [
                        lifecycle_revision_change(
                            "actor_profile",
                            profile.actor_profile_id,
                            status="active",
                            source_ref="revision:no-op",
                        )
                    ],
                    source_ref="revision:no-op",
                )

            change = lifecycle_revision_change(
                "actor_profile",
                profile.actor_profile_id,
                status="deprecated",
                valid_until="003",
                source_ref="revision:profile-deprecation",
                authority="editorial_review",
            )
            preview = service.preview(
                "Deprecate Mina's old goal",
                [change],
                source_ref="revision:profile-deprecation",
            )

            self.assertEqual(repo.list_tickets(), [])
            self.assertEqual(
                repo.list_actor_profiles(actor.entity_id)[0].payload,
                original_payload,
            )
            self.assertEqual(
                repo.list_actor_profiles(actor.entity_id)[0].status,
                "active",
            )
            self.assertIn("expected_revision", preview.changes[0])

            ticket = service.write_ticket(preview)
            self.assertEqual(
                repo.list_actor_profiles(actor.entity_id)[0].status,
                "active",
            )
            review_ticket(repo, ticket.ticket_id)
            self.assertEqual(
                repo.list_actor_profiles(actor.entity_id)[0].status,
                "active",
            )
            applied = apply_ticket(repo, ticket.ticket_id)

            self.assertEqual(applied.applied_ids, [profile.actor_profile_id])
            revised = repo.list_actor_profiles(actor.entity_id)[0]
            self.assertEqual(revised.status, "deprecated")
            self.assertEqual(revised.payload["summary"], original_payload["summary"])
            self.assertEqual(revised.payload["custom"], {"keep": True})
            metadata = revised.payload["_wsa"]
            self.assertEqual(metadata["source_ref"], "seed:profile")
            self.assertEqual(metadata["authority"], "canon")
            self.assertEqual(metadata["valid_until"], "003")
            history = metadata["lifecycle_history"][-1]
            self.assertEqual(history["source_ref"], "revision:profile-deprecation")
            self.assertEqual(history["authority"], "editorial_review")
            self.assertEqual(
                history["before"],
                {"status": "active", "valid_from": "001", "valid_until": None},
            )
            self.assertEqual(
                history["after"],
                {
                    "status": "deprecated",
                    "valid_from": "001",
                    "valid_until": "003",
                },
            )

    def test_interval_revision_changes_context_builder_visibility(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Interval Revision World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ren")
            span = repo.set_entity_attribute_span(
                actor.entity_id,
                "condition",
                value_text="ready",
                valid_from="001",
                status="canon",
                payload={
                    "note": "retain this content",
                    "_wsa": {
                        "source_ref": "seed:condition",
                        "authority": "canon",
                        "valid_from": "001",
                        "valid_until": None,
                    },
                },
            )
            builder = ContextBuilder(repo)
            service = DeepAuthoringService(repo)

            before = builder.build_actor_context(
                actor,
                "scene-003",
                "check readiness",
                time_scope="003",
                persist=False,
            )
            self.assertEqual(
                before["temporal_attributes"][0]["attribute_span_id"],
                span.attribute_span_id,
            )

            preview = service.preview(
                "Close Ren's ready interval",
                [
                    lifecycle_revision_change(
                        "entity_attribute_span",
                        span.attribute_span_id,
                        valid_until="002",
                        source_ref="revision:condition-window",
                    )
                ],
                source_ref="revision:condition-window",
            )
            still_visible = builder.build_actor_context(
                actor,
                "scene-003",
                "check readiness",
                time_scope="003",
                persist=False,
            )
            self.assertEqual(len(still_visible["temporal_attributes"]), 1)

            ticket = service.write_ticket(preview)
            review_ticket(repo, ticket.ticket_id)
            self.assertEqual(
                len(
                    builder.build_actor_context(
                        actor,
                        "scene-003",
                        "check readiness",
                        time_scope="003",
                        persist=False,
                    )["temporal_attributes"]
                ),
                1,
            )
            apply_ticket(repo, ticket.ticket_id)

            at_start = builder.build_actor_context(
                actor,
                "scene-001",
                "check readiness",
                time_scope="001",
                persist=False,
            )
            after_end = builder.build_actor_context(
                actor,
                "scene-003",
                "check readiness",
                time_scope="003",
                persist=False,
            )
            self.assertEqual(len(at_start["temporal_attributes"]), 1)
            self.assertEqual(after_end["temporal_attributes"], [])
            revised = repo.query_entity_attribute_spans(actor.entity_id)[0]
            self.assertEqual(revised.status, "canon")
            self.assertEqual(revised.valid_until, "002")
            self.assertEqual(revised.payload["note"], "retain this content")
            self.assertEqual(revised.payload["_wsa"]["valid_until"], "002")

    def test_replacement_updates_old_record_and_adds_new_record_in_one_ticket(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Replacement World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Sol")
            old = repo.create_actor_profile(
                actor.entity_id,
                "goal",
                {
                    "summary": "Guard the north gate.",
                    "_wsa": {
                        "source_ref": "seed:old-goal",
                        "authority": "canon",
                        "valid_from": "001",
                        "valid_until": None,
                    },
                },
                status="active",
            )
            source_ref = "revision:replace-goal"
            replacement = actor_profile_change(
                actor.entity_id,
                "goal",
                {"summary": "Escort the envoy."},
                valid_from="005",
                source_ref=source_ref,
            )
            changes = deep_record_replacement_changes(
                "actor_profile",
                old.actor_profile_id,
                replacement,
                valid_until="005",
                source_ref=source_ref,
            )
            service = DeepAuthoringService(repo)

            preview = service.preview(
                "Replace Sol's active goal",
                changes,
                source_ref=source_ref,
            )
            self.assertEqual(
                [item["change_type"] for item in preview.changes],
                ["update_actor_profile", "add_actor_profile"],
            )
            self.assertEqual(len(repo.list_actor_profiles(actor.entity_id)), 1)

            ticket = service.write_ticket(preview)
            review_ticket(repo, ticket.ticket_id)
            result = apply_ticket(repo, ticket.ticket_id)

            profiles = repo.list_actor_profiles(actor.entity_id)
            self.assertEqual(len(profiles), 2)
            old_record = next(
                item for item in profiles if item.actor_profile_id == old.actor_profile_id
            )
            new_record = next(
                item for item in profiles if item.actor_profile_id != old.actor_profile_id
            )
            self.assertEqual(old_record.status, "deprecated")
            self.assertEqual(old_record.payload["_wsa"]["valid_until"], "005")
            self.assertEqual(new_record.status, "active")
            self.assertEqual(new_record.payload["summary"], "Escort the envoy.")
            self.assertEqual(result.applied_ids[0], old.actor_profile_id)
            self.assertIn(new_record.actor_profile_id, result.applied_ids)

    def test_wrong_world_missing_and_changed_targets_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            first_world = create_world(workspace, "First Lifecycle World")
            second_world = create_world(workspace, "Second Lifecycle World")
            first_repo = WorldRepository(first_world.world_id, first_world.path)
            second_repo = WorldRepository(second_world.world_id, second_world.path)
            first_actor = first_repo.create_entity("character", "Ira")
            second_repo.create_entity("character", "Nia")
            profile = first_repo.create_actor_profile(
                first_actor.entity_id,
                "goal",
                {"summary": "Find the archive."},
                status="active",
            )

            with self.assertRaises(KeyError):
                DeepAuthoringService(second_repo).preview(
                    "Wrong-world lifecycle target",
                    [
                        lifecycle_revision_change(
                            "actor_profile",
                            profile.actor_profile_id,
                            status="deprecated",
                            source_ref="revision:wrong-world",
                        )
                    ],
                    source_ref="revision:wrong-world",
                )
            with self.assertRaises(KeyError):
                DeepAuthoringService(first_repo).preview(
                    "Missing lifecycle target",
                    [
                        lifecycle_revision_change(
                            "actor_profile",
                            "profile_missing",
                            status="deprecated",
                            source_ref="revision:missing",
                        )
                    ],
                    source_ref="revision:missing",
                )

            service = DeepAuthoringService(first_repo)
            review_missing = service.write_ticket(
                service.preview(
                    "Target removed before review",
                    [
                        lifecycle_revision_change(
                            "actor_profile",
                            profile.actor_profile_id,
                            status="deprecated",
                            source_ref="revision:removed-before-review",
                        )
                    ],
                    source_ref="revision:removed-before-review",
                )
            )
            with sqlite_connection(world_db_path(first_world.path)) as conn:
                conn.execute(
                    "DELETE FROM actor_profiles WHERE actor_profile_id = ?",
                    (profile.actor_profile_id,),
                )
                conn.commit()
            with self.assertRaises(KeyError):
                review_ticket(first_repo, review_missing.ticket_id)
            self.assertEqual(first_repo.get_ticket(review_missing.ticket_id).status, "proposed")

            changed = first_repo.create_actor_profile(
                first_actor.entity_id,
                "goal",
                {"summary": "Cross the strait."},
                status="active",
            )
            changed_ticket = service.write_ticket(
                service.preview(
                    "Target changes before apply",
                    [
                        lifecycle_revision_change(
                            "actor_profile",
                            changed.actor_profile_id,
                            status="deprecated",
                            source_ref="revision:stale",
                        )
                    ],
                    source_ref="revision:stale",
                )
            )
            review_ticket(first_repo, changed_ticket.ticket_id)
            with sqlite_connection(world_db_path(first_world.path)) as conn:
                conn.execute(
                    """
                    UPDATE actor_profiles
                    SET status = 'canon', updated_at = ?
                    WHERE actor_profile_id = ?
                    """,
                    (utc_now(), changed.actor_profile_id),
                )
                conn.commit()
            with self.assertRaises(UnsupportedTicketChangeError):
                apply_ticket(first_repo, changed_ticket.ticket_id)
            self.assertEqual(first_repo.get_ticket(changed_ticket.ticket_id).status, "approved")

            removed = first_repo.create_actor_profile(
                first_actor.entity_id,
                "goal",
                {"summary": "Return before dawn."},
                status="active",
            )
            removed_ticket = service.write_ticket(
                service.preview(
                    "Target removed before apply",
                    [
                        lifecycle_revision_change(
                            "actor_profile",
                            removed.actor_profile_id,
                            status="deprecated",
                            source_ref="revision:removed-before-apply",
                        )
                    ],
                    source_ref="revision:removed-before-apply",
                )
            )
            review_ticket(first_repo, removed_ticket.ticket_id)
            with sqlite_connection(world_db_path(first_world.path)) as conn:
                conn.execute(
                    "DELETE FROM actor_profiles WHERE actor_profile_id = ?",
                    (removed.actor_profile_id,),
                )
                conn.commit()
            with self.assertRaises(KeyError):
                apply_ticket(first_repo, removed_ticket.ticket_id)
            self.assertEqual(first_repo.get_ticket(removed_ticket.ticket_id).status, "approved")

    def test_knowledge_and_memory_lifecycle_fields_are_typed_and_audited(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Typed Lifecycle World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Tala")
            fact = repo.create_fact(
                world.world_id,
                "signal",
                "three short flashes",
                authority="canon",
                status="canon",
            )
            knowledge = repo.add_knowledge_attribution(
                actor.entity_id,
                "fact",
                fact.fact_id,
                "known",
                acquired_at="001",
                status="canon",
                payload={"note": "retain knowledge note"},
            )
            memory = repo.create_actor_memory_packet(
                actor.entity_id,
                "001",
                {"summary": "Saw the signal.", "marker": "keep"},
                status="active",
            )
            changes = [
                lifecycle_revision_change(
                    "knowledge_attribution",
                    knowledge.knowledge_id,
                    acquired_at="002",
                    valid_until="004",
                    source_ref="revision:knowledge-window",
                ),
                lifecycle_revision_change(
                    "actor_memory_packet",
                    memory.memory_packet_id,
                    time_scope="002",
                    valid_until="004",
                    status="rejected",
                    source_ref="revision:memory-window",
                ),
            ]
            self.assertEqual(
                [item["change_type"] for item in changes],
                ["update_knowledge_attribution", "update_actor_memory_packet"],
            )
            service = DeepAuthoringService(repo)
            ticket = service.write_ticket(
                service.preview(
                    "Revise knowledge and memory windows",
                    changes,
                    source_ref="revision:typed-records",
                )
            )
            review_ticket(repo, ticket.ticket_id)
            apply_ticket(repo, ticket.ticket_id)

            revised_knowledge = repo.query_knowledge_attributions(
                actor_entity_id=actor.entity_id
            )[0]
            revised_memory = repo.list_actor_memory_packets(actor.entity_id)[0]
            self.assertEqual(revised_knowledge.status, "canon")
            self.assertEqual(revised_knowledge.acquired_at, "002")
            self.assertEqual(revised_knowledge.valid_until, "004")
            self.assertEqual(
                revised_knowledge.payload["note"],
                "retain knowledge note",
            )
            self.assertEqual(
                revised_knowledge.payload["_wsa"]["lifecycle_history"][-1][
                    "before"
                ]["acquired_at"],
                "001",
            )
            self.assertEqual(revised_memory.status, "rejected")
            self.assertEqual(revised_memory.time_scope, "002")
            self.assertEqual(revised_memory.payload["marker"], "keep")
            self.assertEqual(revised_memory.payload["_wsa"]["valid_until"], "004")

    def test_later_failure_rolls_back_earlier_lifecycle_update(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Lifecycle Rollback World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Oren")
            old = repo.create_actor_profile(
                actor.entity_id,
                "goal",
                {
                    "summary": "Hold the bridge.",
                    "_wsa": {
                        "source_ref": "seed:rollback",
                        "authority": "canon",
                        "valid_from": "001",
                        "valid_until": None,
                    },
                },
                status="active",
            )
            source_ref = "revision:rollback"
            changes = deep_record_replacement_changes(
                "actor_profile",
                old.actor_profile_id,
                actor_profile_change(
                    actor.entity_id,
                    "goal",
                    {"summary": "Leave the bridge."},
                    source_ref=source_ref,
                ),
                source_ref=source_ref,
            )
            service = DeepAuthoringService(repo)
            ticket = service.write_ticket(
                service.preview(
                    "Rollback a failed replacement",
                    changes,
                    source_ref=source_ref,
                )
            )
            review_ticket(repo, ticket.ticket_id)
            with sqlite_connection(world_db_path(world.path)) as conn:
                conn.execute(
                    """
                    CREATE TRIGGER reject_lifecycle_replacement
                    BEFORE INSERT ON actor_profiles
                    BEGIN
                        SELECT RAISE(ABORT, 'forced replacement rejection');
                    END
                    """
                )
                conn.commit()

            with self.assertRaises(IntegrityError):
                apply_ticket(repo, ticket.ticket_id)

            profiles = repo.list_actor_profiles(actor.entity_id)
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].actor_profile_id, old.actor_profile_id)
            self.assertEqual(profiles[0].status, "active")
            self.assertNotIn(
                "lifecycle_history",
                profiles[0].payload["_wsa"],
            )
            self.assertEqual(repo.get_ticket(ticket.ticket_id).status, "approved")
