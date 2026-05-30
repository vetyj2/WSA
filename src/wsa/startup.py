from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .paths import safe_child_path
from .workspace import WorldRecord, utc_now


STARTUP_PROFILE_SCHEMA = "wsa.world_startup.profile.v1"
RESOLVED_STATUSES = {"answered_by_author", "approved_by_author"}
QUESTION_STATUSES = {
    "unasked",
    "asked",
    "answered_by_author",
    "proposed_by_agent",
    "approved_by_author",
    "rejected_by_author",
    "needs_retry",
    "deferred_optional",
}


DEFAULT_STARTUP_DIMENSIONS = [
    {
        "question_id": "Q001",
        "dimension": "premise_genre_tone",
        "prompt": "What kind of world is this, and what tone should early scenes carry?",
        "weight": 10,
    },
    {
        "question_id": "Q002",
        "dimension": "era_daily_life",
        "prompt": "What does ordinary daily life look like in the opening era?",
        "weight": 10,
    },
    {
        "question_id": "Q003",
        "dimension": "magic_access_limits",
        "prompt": "Who can use magic or power, what does it cost, and what can it not solve?",
        "weight": 10,
    },
    {
        "question_id": "Q004",
        "dimension": "core_institutions",
        "prompt": "Which institutions visibly shape power in the opening stage?",
        "weight": 10,
    },
    {
        "question_id": "Q005",
        "dimension": "conflict_engine",
        "prompt": "What pressure makes the story move now instead of staying static?",
        "weight": 10,
    },
    {
        "question_id": "Q006",
        "dimension": "pov_anchor",
        "prompt": "Who is the first POV character or POV role, and what is their initial problem?",
        "weight": 10,
    },
    {
        "question_id": "Q007",
        "dimension": "first_stage_geography",
        "prompt": "Where does the opening happen, and which nearby places matter first?",
        "weight": 10,
    },
    {
        "question_id": "Q008",
        "dimension": "social_economic_baseline",
        "prompt": "How do ordinary people work, travel, communicate, and pay for things?",
        "weight": 10,
    },
    {
        "question_id": "Q009",
        "dimension": "hidden_truth_reveal_policy",
        "prompt": "What hidden truth exists, who knows it, and when should it be revealed?",
        "weight": 10,
    },
    {
        "question_id": "Q010",
        "dimension": "opening_incident",
        "prompt": "What first incident makes the world active for the story?",
        "weight": 10,
    },
]


DEFAULT_MEETING_BUCKETS = [
    {
        "bucket_id": "M001",
        "topic": "institution_set",
        "prompt": "Draft major universities, guilds, or institutions consistent with current answers.",
    },
    {
        "bucket_id": "M002",
        "topic": "power_economy",
        "prompt": "Draft plausible everyday power-system tools, costs, and economic effects.",
    },
    {
        "bucket_id": "M003",
        "topic": "opening_options",
        "prompt": "Draft three possible opening incidents that fit the startup answers.",
    },
]


@dataclass(frozen=True)
class StartupStatus:
    startup_ambiguity_percent: int
    required_total: int
    required_resolved: int
    startup_ready: bool
    profile_path: Path


@dataclass(frozen=True)
class StartupInterviewRound:
    round_id: str
    ambiguity_before: int
    question_budget: int
    questions: List[Dict[str, Any]]
    meeting_buckets: List[Dict[str, Any]]


class StartupProfileManager:
    def __init__(self, world: WorldRecord) -> None:
        self.world = world

    @property
    def startup_dir(self) -> Path:
        return safe_child_path(self.world.path, "startup")

    @property
    def profile_path(self) -> Path:
        return safe_child_path(self.startup_dir, "startup_profile.json")

    def load_or_create(self) -> Dict[str, Any]:
        if self.profile_path.exists():
            return self._load()
        profile = {
            "schema": STARTUP_PROFILE_SCHEMA,
            "world_id": self.world.world_id,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "round_counter": 0,
            "description": (
                "Startup ambiguity tracks only required opening-world blockers, "
                "not total universe completeness."
            ),
            "generation_policy": {
                "autonomy_owner": "user_hermes_runtime_dialogue",
                "autonomy_range": {"min": 0, "max": 100},
                "fully_autonomous_generation_allowed": True,
                "checkpoint_style": "natural_language_recommended",
                "checkpoint_examples": [
                    "until 100 characters exist",
                    "until three regions have factions, conflicts, and opening hooks",
                    "until the first academy year has enough institutions for scene play",
                ],
                "canon_policy": (
                    "Agent-generated startup material is a candidate until author-approved "
                    "or accepted by the user's local Hermes runtime policy."
                ),
            },
            "dimensions": [
                {
                    **item,
                    "required_for_startup": True,
                    "status": "unasked",
                    "answer": None,
                    "answered_by": None,
                    "approved_by_author": False,
                    "updated_at": None,
                }
                for item in DEFAULT_STARTUP_DIMENSIONS
            ],
            "meeting_buckets": DEFAULT_MEETING_BUCKETS,
            "rounds": [],
        }
        self._save(profile)
        return profile

    def status(self) -> StartupStatus:
        profile = self.load_or_create()
        return self._status(profile)

    def interview(self, budget: int = 8) -> StartupInterviewRound:
        if budget <= 0:
            raise ValueError("budget must be positive")
        profile = self.load_or_create()
        status = self._status(profile)
        questions = [
            item
            for item in profile["dimensions"]
            if item["required_for_startup"] and item["status"] not in RESOLVED_STATUSES
        ][:budget]
        for item in questions:
            if item["status"] == "unasked":
                item["status"] = "asked"
                item["updated_at"] = utc_now()
        profile["round_counter"] = int(profile.get("round_counter", 0)) + 1
        round_id = f"R{profile['round_counter']:03d}"
        round_payload = {
            "round_id": round_id,
            "created_at": utc_now(),
            "question_budget": budget,
            "question_ids": [item["question_id"] for item in questions],
            "ambiguity_before": status.startup_ambiguity_percent,
        }
        profile["rounds"].append(round_payload)
        profile["updated_at"] = utc_now()
        self._save(profile)
        return StartupInterviewRound(
            round_id=round_id,
            ambiguity_before=status.startup_ambiguity_percent,
            question_budget=budget,
            questions=questions,
            meeting_buckets=list(profile.get("meeting_buckets", [])),
        )

    def answer(self, question_id: str, text: str, answered_by: str = "author") -> StartupStatus:
        if not text.strip():
            raise ValueError("answer text is required")
        profile = self.load_or_create()
        item = self._dimension_by_question_id(profile, question_id)
        item["answer"] = text.strip()
        item["answered_by"] = answered_by
        item["status"] = "answered_by_author" if answered_by == "author" else "proposed_by_agent"
        item["approved_by_author"] = answered_by == "author"
        item["updated_at"] = utc_now()
        profile["updated_at"] = utc_now()
        self._save(profile)
        return self._status(profile)

    def set_status(self, question_id: str, status: str) -> StartupStatus:
        if status not in QUESTION_STATUSES:
            raise ValueError(f"unsupported startup question status: {status}")
        profile = self.load_or_create()
        item = self._dimension_by_question_id(profile, question_id)
        if status in RESOLVED_STATUSES and not str(item.get("answer") or "").strip():
            raise ValueError("resolved startup question status requires an answer")
        item["status"] = status
        item["approved_by_author"] = status == "approved_by_author"
        item["updated_at"] = utc_now()
        profile["updated_at"] = utc_now()
        self._save(profile)
        return self._status(profile)

    def _status(self, profile: Dict[str, Any]) -> StartupStatus:
        required = [
            item for item in profile["dimensions"] if item.get("required_for_startup") is True
        ]
        total_weight = sum(int(item["weight"]) for item in required)
        unresolved_weight = sum(
            int(item["weight"])
            for item in required
            if item.get("status") not in RESOLVED_STATUSES
        )
        resolved_count = sum(1 for item in required if item.get("status") in RESOLVED_STATUSES)
        ambiguity = int(round((unresolved_weight / total_weight) * 100)) if total_weight else 0
        return StartupStatus(
            startup_ambiguity_percent=ambiguity,
            required_total=len(required),
            required_resolved=resolved_count,
            startup_ready=ambiguity == 0,
            profile_path=self.profile_path,
        )

    def _dimension_by_question_id(self, profile: Dict[str, Any], question_id: str) -> Dict[str, Any]:
        for item in profile["dimensions"]:
            if item["question_id"] == question_id:
                return item
        raise KeyError(f"startup question not found: {question_id}")

    def _load(self) -> Dict[str, Any]:
        value = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != STARTUP_PROFILE_SCHEMA:
            raise ValueError(f"unsupported startup profile schema: {self.profile_path}")
        return value

    def _save(self, profile: Dict[str, Any]) -> None:
        self.startup_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def format_startup_status(status: StartupStatus) -> List[str]:
    return [
        f"startup_ambiguity: {status.startup_ambiguity_percent}%",
        f"required_resolved: {status.required_resolved}/{status.required_total}",
        f"startup_ready: {'yes' if status.startup_ready else 'no'}",
        f"profile_path: {status.profile_path}",
    ]


def format_startup_interview(round_: StartupInterviewRound) -> List[str]:
    lines = [
        f"startup_interview_round: {round_.round_id}",
        f"startup_ambiguity_before: {round_.ambiguity_before}%",
        f"question_budget: {round_.question_budget}",
        "required_for_startup:",
    ]
    lines.extend(
        "\t".join(
            [
                item["question_id"],
                item["status"],
                item["dimension"],
                item["prompt"],
            ]
        )
        for item in round_.questions
    )
    lines.append("deferred_to_meeting:")
    lines.extend(
        "\t".join([item["bucket_id"], item["topic"], item["prompt"]])
        for item in round_.meeting_buckets
    )
    return lines
