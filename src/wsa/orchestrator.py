from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .actors import MockActorRuntime
from .context import ContextBuilder
from .ids import slugify
from .paths import safe_child_path
from .reports import ReportMailbox
from .repositories import EntityRecord, WorldRepository
from .tickets import create_pr_packet
from .transport import RuntimeTransport
from .workspace import WorldRecord


@dataclass(frozen=True)
class MockSceneResult:
    scene_id: str
    scene_dir: Path
    prep_receipt: Path
    progress_checkpoint: Path
    ticket_id: str
    report_id: str
    orchestrator_session_id: str
    actor_session_ids: List[str]


class SceneOrchestrator:
    def __init__(self, workspace: Path, world: WorldRecord) -> None:
        self.workspace = workspace
        self.world = world
        self.repo = WorldRepository(world.world_id, world.path)
        self.transport = RuntimeTransport(workspace)
        self.mailbox = ReportMailbox(workspace)

    def run_mock_scene(
        self,
        scene_name: str,
        scene_goal: str,
        actors: Iterable[EntityRecord],
    ) -> MockSceneResult:
        actor_list = list(actors)
        scene = self.repo.create_scene(
            scene_name,
            payload={"goal": scene_goal, "mode": "mock"},
            status="running",
        )
        scene_dir = safe_child_path(
            self.world.path,
            "scenes",
            f"{slugify(scene_name)}_{scene.scene_id[:14]}",
        )
        tmp_dir = safe_child_path(scene_dir, "tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)

        initiation_queue = [
            {
                "actor_id": actor.entity_id,
                "actor_name": actor.display_name,
                "request": "propose_action",
            }
            for actor in actor_list
        ]
        prep_receipt = safe_child_path(tmp_dir, "prep_receipt.json")
        prep_receipt.write_text(
            json.dumps(
                {
                    "world_id": self.world.world_id,
                    "scene_id": scene.scene_id,
                    "scene_name": scene_name,
                    "scene_goal": scene_goal,
                    "actors": [actor.entity_id for actor in actor_list],
                    "initiation_queue": initiation_queue,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        orchestrator_session_id = self.transport.start_session(
            role="orchestrator",
            runtime_target="mock",
            world_id=self.world.world_id,
            scene_id=scene.scene_id,
            payload={"scene_name": scene_name},
        )
        self.transport.send(
            orchestrator_session_id,
            "inbox",
            role="world_manager",
            message_type="context_assignment",
            world_id=self.world.world_id,
            scene_id=scene.scene_id,
            payload={"scene_goal": scene_goal, "initiation_queue": initiation_queue},
            artifact_refs=[str(prep_receipt)],
        )

        runtime = MockActorRuntime()
        context_builder = ContextBuilder(self.repo)
        actor_session_ids: List[str] = []
        proposals = []
        for actor in actor_list:
            actor_session_id = self.transport.start_session(
                role="actor",
                runtime_target="mock",
                world_id=self.world.world_id,
                scene_id=scene.scene_id,
                payload={"actor_id": actor.entity_id},
            )
            actor_session_ids.append(actor_session_id)
            context_packet = context_builder.build_actor_context(
                actor,
                scene.scene_id,
                scene_goal,
            )
            self.transport.send(
                actor_session_id,
                "inbox",
                role="orchestrator",
                message_type="context_assignment",
                world_id=self.world.world_id,
                scene_id=scene.scene_id,
                payload=context_packet,
            )
            proposal = runtime.propose(actor, scene_goal)
            proposals.append(proposal)
            self.transport.send(
                actor_session_id,
                "outbox",
                role="actor",
                message_type=proposal.response_type,
                world_id=self.world.world_id,
                scene_id=scene.scene_id,
                payload=proposal.payload,
            )

        committed_payload = {
            "accepted_proposals": [proposal.payload for proposal in proposals[:1]],
            "summary": "Mock scene committed its first accepted actor proposal.",
        }
        event_id = self.repo.add_scene_event(
            scene.scene_id,
            "mock_event",
            payload=committed_payload,
        )
        self.repo.append_commit(
            "scene_event_committed",
            "scene_event",
            event_id,
            payload={"scene_id": scene.scene_id},
        )

        progress_checkpoint = safe_child_path(tmp_dir, "progress_0001.json")
        progress_checkpoint.write_text(
            json.dumps(
                {
                    "scene_id": scene.scene_id,
                    "summary": committed_payload["summary"],
                    "committed_event_id": event_id,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.transport.send(
            orchestrator_session_id,
            "outbox",
            role="orchestrator",
            message_type="progress_summary",
            world_id=self.world.world_id,
            scene_id=scene.scene_id,
            payload={"summary": committed_payload["summary"], "event_id": event_id},
            artifact_refs=[str(progress_checkpoint)],
        )

        ticket = create_pr_packet(
            self.repo,
            title=f"Scene result PR: {scene_name}",
            changes=[
                {
                    "change_type": "add_fact",
                    "target_type": "fact",
                    "subject_id": actor_list[0].entity_id if actor_list else scene.scene_id,
                    "predicate": "appeared_in_scene",
                    "object_value": scene_name,
                    "authority": "scene_generated",
                    "status": "proposed",
                    "source_ref": scene.scene_id,
                }
            ],
            compact=True,
        )
        self.transport.send(
            orchestrator_session_id,
            "outbox",
            role="orchestrator",
            message_type="pr_packet_request",
            world_id=self.world.world_id,
            scene_id=scene.scene_id,
            payload={"ticket_id": ticket.ticket_id},
        )

        report = self.mailbox.create_world_report(
            self.repo,
            title=f"Final scene report: {scene_name}",
            purpose="post_scene",
            risk="low",
            status="inbox",
            payload={
                "scene_id": scene.scene_id,
                "event_id": event_id,
                "ticket_id": ticket.ticket_id,
                "summary": committed_payload["summary"],
            },
        )
        self.transport.send(
            orchestrator_session_id,
            "outbox",
            role="orchestrator",
            message_type="final_report",
            world_id=self.world.world_id,
            scene_id=scene.scene_id,
            payload={"report_id": report.report_id},
            artifact_refs=[report.artifact_ref] if report.artifact_ref else [],
        )

        return MockSceneResult(
            scene_id=scene.scene_id,
            scene_dir=scene_dir,
            prep_receipt=prep_receipt,
            progress_checkpoint=progress_checkpoint,
            ticket_id=ticket.ticket_id,
            report_id=report.report_id,
            orchestrator_session_id=orchestrator_session_id,
            actor_session_ids=actor_session_ids,
        )
