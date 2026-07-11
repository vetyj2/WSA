from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.application.deep_authoring_service import (
    DeepAuthoringService,
    actor_memory_change,
    actor_profile_change,
    knowledge_attribution_change,
    temporal_attribute_change,
)
from wsa.application.proposal_service import (
    portable_import_preview,
    write_proposal_ticket,
)
from wsa.application.world_fork_service import WorldForkService
from wsa.application.world_service import WorldInspectionService
from wsa.context import ContextBuilder
from wsa.repositories import WorldRepository
from wsa.tickets import (
    UnsupportedTicketChangeError,
    apply_ticket,
    review_ticket,
)
from wsa.workspace import create_world


class PortableDeepRoundTripTests(TestCase):
    def test_deep_authoring_round_trip_preserves_refs_time_and_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            source = create_world(workspace, "Portable Deep Source")
            source_repo = WorldRepository(source.world_id, source.path)
            actor = source_repo.create_entity("character", "Mina")
            hidden_fact = source_repo.create_fact(
                source.world_id,
                "hidden_signal",
                "the beacon is forged",
                authority="canon",
                status="canon",
                payload={"visibility": "hidden"},
            )
            source_ref = "author-session:portable-deep"
            service = DeepAuthoringService(source_repo)
            deep_preview = service.preview(
                "Build portable actor state",
                [
                    actor_profile_change(
                        actor.entity_id,
                        "goal",
                        {"summary": "Reach the signal tower."},
                        source_ref=source_ref,
                    ),
                    temporal_attribute_change(
                        actor.entity_id,
                        "condition",
                        value_text="wounded",
                        valid_from="002",
                        valid_until="004",
                        source_ref=source_ref,
                    ),
                    knowledge_attribution_change(
                        actor.entity_id,
                        "fact",
                        hidden_fact.fact_id,
                        "known",
                        acquired_at="002",
                        source_ref=source_ref,
                    ),
                    actor_memory_change(
                        actor.entity_id,
                        "002",
                        {"summary": "Heard the first shot."},
                        source_ref=source_ref,
                    ),
                ],
                source_ref=source_ref,
            )
            deep_ticket = service.write_ticket(deep_preview)
            review_ticket(source_repo, deep_ticket.ticket_id)
            apply_ticket(source_repo, deep_ticket.ticket_id)

            full_export = WorldInspectionService(source).export_data()
            self.assertEqual(len(full_export["actor_profiles"]), 1)
            self.assertEqual(len(full_export["entity_attribute_spans"]), 1)
            self.assertEqual(len(full_export["knowledge_attributions"]), 1)
            self.assertEqual(len(full_export["actor_memory_packets"]), 1)
            exported = WorldForkService(source).selective_export([actor.entity_id])
            self.assertEqual(len(exported["actor_profiles"]), 1)
            self.assertEqual(len(exported["entity_attribute_spans"]), 1)
            self.assertEqual(len(exported["knowledge_attributions"]), 1)
            self.assertEqual(len(exported["actor_memory_packets"]), 1)
            destination = create_world(workspace, "Portable Deep Destination")
            destination_repo = WorldRepository(destination.world_id, destination.path)
            import_preview = portable_import_preview(destination, exported)
            import_ticket = write_proposal_ticket(destination_repo, import_preview)

            self.assertEqual(destination_repo.list_entities(), [])
            review_ticket(destination_repo, import_ticket.ticket_id)
            self.assertEqual(destination_repo.list_entities(), [])
            apply_ticket(destination_repo, import_ticket.ticket_id)

            imported_actor = destination_repo.get_entity(actor.entity_id)
            imported_fact = destination_repo.get_fact(hidden_fact.fact_id)
            profile = destination_repo.list_actor_profiles(actor.entity_id)[0]
            span = destination_repo.query_entity_attribute_spans(actor.entity_id)[0]
            knowledge = destination_repo.query_knowledge_attributions(actor.entity_id)[0]
            memory = destination_repo.list_actor_memory_packets(actor.entity_id)[0]

            self.assertEqual(imported_actor.display_name, "Mina")
            self.assertEqual(imported_fact.payload["visibility"], "hidden")
            self.assertEqual(profile.payload["_wsa"]["source_ref"], source_ref)
            self.assertEqual(span.valid_from, "002")
            self.assertEqual(span.valid_until, "004")
            self.assertEqual(span.payload["_wsa"]["source_ref"], source_ref)
            self.assertEqual(knowledge.target_id, hidden_fact.fact_id)
            self.assertEqual(knowledge.acquired_at, "002")
            self.assertEqual(memory.time_scope, "002")
            self.assertEqual(memory.payload["_wsa"]["source_ref"], source_ref)

            context = ContextBuilder(destination_repo).build_actor_context(
                imported_actor,
                "scene-002",
                "inspect the hidden signal",
                time_scope="002",
                persist=False,
            )
            self.assertEqual(context["facts"][0]["fact_id"], hidden_fact.fact_id)
            self.assertEqual(
                context["temporal_attributes"][0]["value_text"],
                "wounded",
            )

            counts_before_collision = (
                len(destination_repo.list_entities()),
                len(destination_repo.list_facts()),
                len(destination_repo.list_actor_profiles(actor.entity_id)),
            )
            collision_ticket = write_proposal_ticket(
                destination_repo,
                portable_import_preview(destination, exported),
            )
            with self.assertRaisesRegex(
                UnsupportedTicketChangeError,
                "portable ID collision",
            ):
                review_ticket(destination_repo, collision_ticket.ticket_id)
            self.assertEqual(destination_repo.get_ticket(collision_ticket.ticket_id).status, "proposed")
            self.assertEqual(
                (
                    len(destination_repo.list_entities()),
                    len(destination_repo.list_facts()),
                    len(destination_repo.list_actor_profiles(actor.entity_id)),
                ),
                counts_before_collision,
            )
