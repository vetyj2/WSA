from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.repositories import ControlRepository, WorldRepository
from wsa.workspace import control_db_path, create_world, sqlite_connection, world_db_path


CONTROL_TABLES = {
    "worlds",
    "user_profile_entries",
    "manager_memory",
    "runtime_sessions",
    "runtime_messages",
    "global_reports",
    "scheduler_jobs",
    "automation_policies",
}

WORLD_TABLES = {
    "entities",
    "facts",
    "relationships",
    "timeline_points",
    "scenes",
    "scene_events",
    "actor_profiles",
    "actor_memory_packets",
    "context_packets",
    "tickets",
    "ticket_changes",
    "reports",
    "diagnostic_logs",
    "artifact_refs",
    "tags",
    "tag_links",
    "commit_log",
}


def table_names(db_path: Path) -> set[str]:
    with sqlite_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row["name"] for row in rows}


class RepositoryTests(TestCase):
    def test_phase_two_tables_exist(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Schema World")

            self.assertTrue(CONTROL_TABLES.issubset(table_names(control_db_path(workspace))))
            self.assertTrue(WORLD_TABLES.issubset(table_names(world_db_path(world.path))))

    def test_world_repository_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Repo World")
            repo = WorldRepository(world.world_id, world.path)

            actor = repo.create_entity(
                "character",
                "Mina",
                payload={"role": "pilot"},
            )
            fact = repo.create_fact(
                actor.entity_id,
                "has_role",
                "pilot",
                authority="user_explicit",
                status="canon",
                tags=["character", "role"],
            )
            scene = repo.create_scene("Opening", timeline_position="T1")
            event_id = repo.add_scene_event(
                scene.scene_id,
                "dialogue",
                payload={"text": "Ready."},
            )
            ticket = repo.create_ticket(
                "Promote opening fact",
                payload={"facts": [fact.fact_id]},
            )
            report = repo.create_report(
                "Opening report",
                purpose="post_scene",
                payload={"ticket_id": ticket.ticket_id},
            )
            commit_id = repo.append_commit(
                "ticket_created",
                "ticket",
                ticket.ticket_id,
            )

            facts = repo.list_facts(actor.entity_id)
            entities = repo.list_entities(entity_type="character", status="active")
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0].predicate, "has_role")
            self.assertEqual([item.display_name for item in entities], ["Mina"])
            self.assertTrue(event_id.startswith("event_"))
            self.assertTrue(report.report_id.startswith("report_"))
            self.assertTrue(commit_id.startswith("commit_"))

    def test_control_repository_runtime_messages_are_sequenced(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Runtime World")
            control = ControlRepository(workspace)
            session = control.create_runtime_session(
                role="orchestrator",
                world_id=world.world_id,
                runtime_target="mock",
            )

            first = control.add_runtime_message(
                session.session_id,
                role="manager",
                message_type="context_assignment",
                world_id=world.world_id,
                payload={"goal": "test"},
            )
            second = control.add_runtime_message(
                session.session_id,
                role="orchestrator",
                message_type="progress_summary",
                world_id=world.world_id,
                payload={"summary": "started"},
            )

            messages = control.list_runtime_messages(session.session_id)
            self.assertEqual([item.sequence for item in messages], [1, 2])
            self.assertEqual(first.sequence, 1)
            self.assertEqual(second.sequence, 2)
            self.assertEqual(messages[0].payload["goal"], "test")
