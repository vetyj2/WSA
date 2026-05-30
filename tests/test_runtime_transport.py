from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.paths import UnsafePathError, safe_child_path
from wsa.runtime import (
    InvalidDirectionError,
    InvalidMessageTypeError,
    RuntimeEnvelope,
    RuntimeRouteError,
)
from wsa.transport import RuntimeTransport
from wsa.workspace import create_world


class RuntimeTransportTests(TestCase):
    def test_envelope_round_trip(self) -> None:
        envelope = RuntimeEnvelope(
            message_id="msg_1",
            protocol_version=1,
            workspace_id="local",
            world_id="world_1",
            scene_id="scene_1",
            session_id="session_1",
            role="orchestrator",
            message_type="context_assignment",
            sequence=1,
            payload={"goal": "test"},
            artifact_refs=["artifact_1"],
            status="queued",
        )

        restored = RuntimeEnvelope.from_dict(envelope.to_dict())
        self.assertEqual(restored, envelope)

    def test_invalid_message_type_is_rejected(self) -> None:
        with self.assertRaises(InvalidMessageTypeError):
            RuntimeEnvelope(
                message_id="msg_1",
                protocol_version=1,
                workspace_id="local",
                world_id=None,
                scene_id=None,
                session_id="session_1",
                role="actor",
                message_type="freeform_unknown",
                sequence=1,
            )

    def test_filesystem_transport_writes_inbox_and_outbox(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Transport World")
            transport = RuntimeTransport(workspace)
            session_id = transport.start_session(
                role="orchestrator",
                world_id=world.world_id,
                runtime_target="mock",
            )

            inbound = transport.send(
                session_id=session_id,
                direction="inbox",
                role="manager",
                message_type="context_assignment",
                world_id=world.world_id,
                payload={"goal": "open scene"},
            )
            outbound = transport.send(
                session_id=session_id,
                direction="outbox",
                role="orchestrator",
                message_type="progress_summary",
                world_id=world.world_id,
                payload={"summary": "started"},
            )

            inbox = transport.list_envelopes(session_id, "inbox")
            outbox = transport.list_envelopes(session_id, "outbox")

            self.assertEqual([item.message_id for item in inbox], [inbound.message_id])
            self.assertEqual([item.message_id for item in outbox], [outbound.message_id])
            self.assertEqual(inbox[0].world_id, world.world_id)
            self.assertEqual(outbox[0].payload["summary"], "started")

    def test_world_bound_session_defaults_and_rejects_route_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Routed World")
            other_world = create_world(workspace, "Other World")
            transport = RuntimeTransport(workspace)
            session_id = transport.start_session(
                role="orchestrator",
                world_id=world.world_id,
                scene_id="scene_routed",
            )

            envelope = transport.send(
                session_id=session_id,
                direction="inbox",
                role="manager",
                message_type="context_assignment",
            )

            self.assertEqual(envelope.world_id, world.world_id)
            self.assertEqual(envelope.scene_id, "scene_routed")
            with self.assertRaises(RuntimeRouteError):
                transport.send(
                    session_id=session_id,
                    direction="inbox",
                    role="manager",
                    message_type="context_assignment",
                    world_id=other_world.world_id,
                )
            with self.assertRaises(RuntimeRouteError):
                transport.send(
                    session_id=session_id,
                    direction="inbox",
                    role="manager",
                    message_type="context_assignment",
                    scene_id="scene_wrong",
                )

    def test_invalid_direction_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "Direction World")
            transport = RuntimeTransport(workspace)
            session_id = transport.start_session(role="actor")

            with self.assertRaises(InvalidDirectionError):
                transport.send(
                    session_id=session_id,
                    direction="elsewhere",
                    role="actor",
                    message_type="inner_thought",
                )

    def test_path_traversal_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            base.mkdir()

            with self.assertRaises(UnsafePathError):
                safe_child_path(base, "..", "escape.json")
            with self.assertRaises(UnsafePathError):
                safe_child_path(base, "/tmp/escape.json")

    def test_tmp_cleanup_only_removes_tmp_files(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Cleanup World")
            transport = RuntimeTransport(workspace)
            session_id = transport.start_session(role="orchestrator", world_id=world.world_id)

            transport.send(
                session_id=session_id,
                direction="inbox",
                role="manager",
                message_type="intent_request",
                world_id=world.world_id,
            )
            tmp_path = transport.write_tmp(
                session_id,
                "scratch",
                {"temporary": True},
            )

            self.assertTrue(tmp_path.exists())
            removed = transport.cleanup_tmp(session_id)

            self.assertEqual(removed, 1)
            self.assertFalse(tmp_path.exists())
            self.assertEqual(len(transport.list_envelopes(session_id, "inbox")), 1)
