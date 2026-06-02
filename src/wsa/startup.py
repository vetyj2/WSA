from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .autonomy import DISCRETION_LEVELS, discretion_scale_contract, fill_the_rest_contract
from .paths import safe_child_path
from .workspace import WorldRecord, utc_now


STARTUP_PROFILE_SCHEMA = "wsa.world_startup.profile.v1"
STARTUP_MODES = {"startup", "easystartup"}
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
ANSWER_CODE_PATTERN = re.compile(r"\bQ?0*(\d{1,4})([a-iA-I])\b")


DEFAULT_STARTUP_DIMENSIONS = [
    {
        "question_id": "0001",
        "legacy_question_id": "Q001",
        "dimension": "premise_genre_tone",
        "startup_prompt": "What is the core promise of the world, and what should remain open?",
        "startup_choices": [
            "Character-first drama with world rules discovered through scenes.",
            "Mystery-forward setting where unknown systems are part of the hook.",
            "Adventure sandbox with broad constraints and room for author invention.",
        ],
        "easystartup_prompt": "Pick the nearest world premise and tone.",
        "easypicks": [
            "institutional mystery drama",
            "frontier political noir",
            "post-collapse recovery drama",
            "mythic expedition adventure",
            "slice-of-life hidden-system city",
            "court intrigue with hidden power systems",
        ],
        "weight": 10,
    },
    {
        "question_id": "0002",
        "legacy_question_id": "Q002",
        "dimension": "era_daily_life",
        "startup_prompt": "What does ordinary daily life roughly look like before the plot disturbs it?",
        "startup_choices": [
            "Mostly familiar daily life with one major speculative exception.",
            "Distinct historical or secondary-world life with many open details.",
            "Unstable era where daily life differs sharply by region or class.",
        ],
        "easystartup_prompt": "Choose the baseline era and everyday texture.",
        "easypicks": [
            "late medieval trade towns",
            "early industrial capital",
            "modern city with hidden speculative systems",
            "far-future orbital habitats",
            "rural frontier settlements",
            "collapsed empire remnant states",
        ],
        "weight": 10,
    },
    {
        "question_id": "0003",
        "legacy_question_id": "Q003",
        "dimension": "power_access_limits",
        "startup_prompt": "Who can use power, what does it cost, and what should it not solve?",
        "startup_choices": [
            "Rare specialists use power under strict costs.",
            "Many people can use small powers, but scale is limited.",
            "Power access is political, institutional, or inherited.",
        ],
        "easystartup_prompt": "Pick the closest power access model.",
        "easypicks": [
            "rare licensed specialists",
            "formal training and licensed craft",
            "bloodline contracts",
            "tool-based public utility power",
            "dangerous relic power",
            "faith or oath-based miracles",
        ],
        "weight": 10,
    },
    {
        "question_id": "0004",
        "legacy_question_id": "Q004",
        "dimension": "core_institutions",
        "startup_prompt": "Which institution visibly shapes the opening stage?",
        "startup_choices": [
            "One dominant school, guild, temple, bureau, or court.",
            "Several rival institutions with unclear jurisdiction.",
            "Weak institutions; families, gangs, or local powers fill the gap.",
        ],
        "easystartup_prompt": "Pick the first institution cluster Hermes should flesh out.",
        "easypicks": [
            "training institute and scholarship board",
            "merchant guild and port authority",
            "temple court and oath registry",
            "central bureau and intelligence office",
            "frontier council and militia",
            "research institute and private sponsors",
        ],
        "weight": 10,
    },
    {
        "question_id": "0005",
        "legacy_question_id": "Q005",
        "dimension": "conflict_engine",
        "startup_prompt": "What pressure makes the story move now instead of staying static?",
        "startup_choices": [
            "A personal problem exposes a larger world fault.",
            "A public crisis forces institutions to act.",
            "A hidden rule changes, and old balances fail.",
        ],
        "easystartup_prompt": "Choose the main engine of early conflict.",
        "easypicks": [
            "succession crisis",
            "forbidden discovery",
            "resource shortage",
            "institutional corruption",
            "border war pressure",
            "ritual or system failure",
        ],
        "weight": 10,
    },
    {
        "question_id": "0006",
        "legacy_question_id": "Q006",
        "dimension": "pov_anchor",
        "startup_prompt": "Who is the first POV role, and what problem makes them move?",
        "startup_choices": [
            "Outsider entering a structured world.",
            "Insider discovering their institution is unstable.",
            "Marginal figure pulled into a decision above their station.",
        ],
        "easystartup_prompt": "Pick the first POV anchor type.",
        "easypicks": [
            "newly admitted student",
            "junior investigator",
            "fallen noble heir",
            "guild apprentice",
            "temple novice",
            "frontier courier",
        ],
        "weight": 10,
    },
    {
        "question_id": "0007",
        "legacy_question_id": "Q007",
        "dimension": "first_stage_geography",
        "startup_prompt": "Where does the opening happen, and what nearby places matter first?",
        "startup_choices": [
            "One dense hub with nearby implied places.",
            "A route across several small locations.",
            "A border zone between two or more cultures or powers.",
        ],
        "easystartup_prompt": "Pick the opening geography package.",
        "easypicks": [
            "capital training district",
            "harbor city and outer islands",
            "frontier pass and border fort",
            "river market towns",
            "desert pilgrimage route",
            "orbital station and lower colony",
        ],
        "weight": 10,
    },
    {
        "question_id": "0008",
        "legacy_question_id": "Q008",
        "dimension": "social_economic_baseline",
        "startup_prompt": "How do ordinary people work, travel, communicate, and pay for things?",
        "startup_choices": [
            "Keep it familiar unless a story scene needs detail.",
            "Define a few visible everyday systems now.",
            "Let economy and class be a major source of conflict.",
        ],
        "easystartup_prompt": "Pick the everyday systems Hermes should prefill.",
        "easypicks": [
            "coin, letters, horse roads",
            "guild scrip, couriers, riverboats",
            "public transit, phones, hidden specialist services",
            "ration cards, salvage markets, radio relays",
            "contract marks, oath records, caravan routes",
            "energy credits, drones, station networks",
        ],
        "weight": 10,
    },
    {
        "question_id": "0009",
        "legacy_question_id": "Q009",
        "dimension": "hidden_truth_reveal_policy",
        "startup_prompt": "What hidden truth exists, who knows it, and how much should remain blank?",
        "startup_choices": [
            "Only define the shape of the secret now.",
            "Define the secret and a small circle of people who know.",
            "Let Hermes propose several candidate secrets for later approval.",
        ],
        "easystartup_prompt": "Pick the hidden-truth handling style.",
        "easypicks": [
            "lost history behind the institution",
            "false public origin myth",
            "power source has a moral cost",
            "ruling family hides a succession lie",
            "monsters are former citizens or agents",
            "the map omits a protected region",
        ],
        "weight": 10,
    },
    {
        "question_id": "0010",
        "legacy_question_id": "Q010",
        "dimension": "opening_incident",
        "startup_prompt": "What first incident makes the world active for the story?",
        "startup_choices": [
            "A small personal incident with larger implications.",
            "A public disruption that changes the local status quo.",
            "A discovery that asks for investigation before action.",
        ],
        "easystartup_prompt": "Pick an opening incident pattern.",
        "easypicks": [
            "student vanishes before examination day",
            "guild shipment arrives cursed",
            "border fort sends impossible distress signal",
            "public ritual fails in front of witnesses",
            "old map names a place no one remembers",
            "ordinary job reveals illegal power use",
        ],
        "weight": 10,
    },
]


DEFAULT_MEETING_BUCKETS = [
    {
        "bucket_id": "M001",
        "topic": "institution_set",
        "prompt": "Draft major institutions, guilds, research bodies, or local powers consistent with current answers.",
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
    progress_percent: int
    remaining_percent: int
    required_total: int
    required_resolved: int
    startup_ready: bool
    active_mode: str
    discretion_level: int
    discretion_label: str
    profile_path: Path


@dataclass(frozen=True)
class StartupInterviewRound:
    round_id: str
    mode: str
    ambiguity_before: int
    progress_before: int
    remaining_after: int
    question_budget: int
    discretion_level: int
    discretion_label: str
    questions: List[Dict[str, Any]]
    next_question: Dict[str, Any] | None
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
            profile = self._load()
            if self._ensure_profile_defaults(profile):
                self._save(profile)
            return profile
        profile = {
            "schema": STARTUP_PROFILE_SCHEMA,
            "world_id": self.world.world_id,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "round_counter": 0,
            "active_mode": "startup",
            "discretion_level": 2,
            "description": (
                "Startup ambiguity tracks only required opening-world blockers, "
                "not total universe completeness."
            ),
            "interview_policy": {
                "question_id_format": "four_digit",
                "answer_code_format": "0001a",
                "parallel_answering": True,
                "return_to_interview_until_stopped": True,
                "startup": {
                    "style": "open_author_frame",
                    "max_choices": 3,
                    "free_text": "long_form_encouraged",
                },
                "easystartup": {
                    "style": "easy_pick_closed_frame",
                    "choice_count": "5_to_8",
                    "agent_detail_fill": "allowed_by_discretion_level",
                },
            },
            "generation_policy": {
                "autonomy_owner": "user_hermes_runtime_dialogue",
                "autonomy_range": {"min": 0, "max": 100},
                "discretion_customizable": True,
                "discretion_scale": discretion_scale_contract(),
                "fill_the_rest": fill_the_rest_contract(),
                "fully_autonomous_generation_allowed": True,
                "checkpoint_style": "natural_language_recommended",
                "checkpoint_examples": [
                    "until 100 characters exist",
                    "until three regions have factions, conflicts, and opening hooks",
                    "until the opening arc has enough institutions for scene play",
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
                    "selected_choice": None,
                    "answered_by": None,
                    "approved_by_author": False,
                    "updated_at": None,
                }
                for item in DEFAULT_STARTUP_DIMENSIONS
            ],
            "freeform_notes": [],
            "meeting_buckets": DEFAULT_MEETING_BUCKETS,
            "rounds": [],
        }
        self._save(profile)
        return profile

    def status(self, mode: str | None = None) -> StartupStatus:
        profile = self.load_or_create()
        active_mode = self._validate_mode(mode) if mode is not None else None
        return self._status(profile, active_mode=active_mode)

    def interview(self, budget: int = 8, mode: str = "startup") -> StartupInterviewRound:
        if budget <= 0:
            raise ValueError("budget must be positive")
        mode = self._validate_mode(mode)
        profile = self.load_or_create()
        profile["active_mode"] = mode
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
        next_question = self._next_unresolved_question(profile, skip_ids={item["question_id"] for item in questions})
        round_payload = {
            "round_id": round_id,
            "mode": mode,
            "created_at": utc_now(),
            "question_budget": budget,
            "question_ids": [item["question_id"] for item in questions],
            "ambiguity_before": status.startup_ambiguity_percent,
            "progress_before": status.progress_percent,
            "discretion_level": status.discretion_level,
        }
        profile["rounds"].append(round_payload)
        profile["updated_at"] = utc_now()
        self._save(profile)
        after = self._status(profile)
        return StartupInterviewRound(
            round_id=round_id,
            mode=mode,
            ambiguity_before=status.startup_ambiguity_percent,
            progress_before=status.progress_percent,
            remaining_after=after.remaining_percent,
            question_budget=budget,
            discretion_level=after.discretion_level,
            discretion_label=after.discretion_label,
            questions=questions,
            next_question=next_question,
            meeting_buckets=list(profile.get("meeting_buckets", [])),
        )

    def answer(
        self,
        question_id: str,
        text: str,
        answered_by: str = "author",
        choice: str | None = None,
        mode: str | None = None,
    ) -> StartupStatus:
        if not text.strip():
            raise ValueError("answer text is required")
        profile = self.load_or_create()
        active_mode = self._validate_mode(mode) if mode is not None else profile.get("active_mode", "startup")
        profile["active_mode"] = active_mode
        item = self._dimension_by_question_id(profile, question_id)
        selected_choice = self._normalize_choice(choice) if choice else None
        if selected_choice is not None:
            self._choice_text(item, active_mode, selected_choice)
        item["answer"] = text.strip()
        item["selected_choice"] = selected_choice
        item["answered_by"] = answered_by
        item["status"] = "answered_by_author" if answered_by == "author" else "proposed_by_agent"
        item["approved_by_author"] = answered_by == "author"
        item["updated_at"] = utc_now()
        profile["updated_at"] = utc_now()
        self._save(profile)
        return self._status(profile)

    def answer_batch(
        self,
        text: str,
        answered_by: str = "author",
        mode: str | None = None,
    ) -> StartupStatus:
        selections, note = parse_startup_answer_text(text)
        if not selections and not note.strip():
            raise ValueError("answer text or answer codes are required")
        profile = self.load_or_create()
        active_mode = self._validate_mode(mode) if mode is not None else profile.get("active_mode", "startup")
        profile["active_mode"] = active_mode
        for question_id, choice in selections:
            item = self._dimension_by_question_id(profile, question_id)
            option = self._choice_text(item, active_mode, choice)
            item["answer"] = f"{choice}) {option}"
            item["selected_choice"] = choice
            item["answered_by"] = answered_by
            item["status"] = "answered_by_author" if answered_by == "author" else "proposed_by_agent"
            item["approved_by_author"] = answered_by == "author"
            item["updated_at"] = utc_now()
        if note.strip():
            profile.setdefault("freeform_notes", []).append(
                {
                    "created_at": utc_now(),
                    "text": note.strip(),
                    "question_ids": [question_id for question_id, _ in selections],
                }
            )
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

    def set_discretion(self, level: int, mode: str | None = None) -> StartupStatus:
        if level not in DISCRETION_LEVELS:
            raise ValueError("discretion level must be between 0 and 5")
        profile = self.load_or_create()
        if mode is not None:
            profile["active_mode"] = self._validate_mode(mode)
        profile["discretion_level"] = level
        profile["updated_at"] = utc_now()
        self._save(profile)
        return self._status(profile)

    def _status(
        self,
        profile: Dict[str, Any],
        active_mode: str | None = None,
    ) -> StartupStatus:
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
        progress = 100 - ambiguity
        discretion_level = int(profile.get("discretion_level", 2))
        return StartupStatus(
            startup_ambiguity_percent=ambiguity,
            progress_percent=progress,
            remaining_percent=ambiguity,
            required_total=len(required),
            required_resolved=resolved_count,
            startup_ready=ambiguity == 0,
            active_mode=str(active_mode or profile.get("active_mode") or "startup"),
            discretion_level=discretion_level,
            discretion_label=DISCRETION_LEVELS.get(discretion_level, "unknown"),
            profile_path=self.profile_path,
        )

    def _dimension_by_question_id(self, profile: Dict[str, Any], question_id: str) -> Dict[str, Any]:
        normalized = normalize_question_id(question_id)
        for item in profile["dimensions"]:
            if normalize_question_id(str(item.get("question_id", ""))) == normalized:
                return item
            if normalize_question_id(str(item.get("legacy_question_id", ""))) == normalized:
                return item
        raise KeyError(f"startup question not found: {question_id}")

    def _choice_text(self, item: Dict[str, Any], mode: str, choice: str) -> str:
        choices = choice_labels_for_question(item, mode)
        for option in choices:
            if option["label"] == choice:
                return option["text"]
        raise ValueError(f"choice {choice} is not available for {item['question_id']}")

    def _next_unresolved_question(
        self,
        profile: Dict[str, Any],
        skip_ids: set[str] | None = None,
    ) -> Dict[str, Any] | None:
        skip_ids = skip_ids or set()
        for item in profile["dimensions"]:
            if item["question_id"] in skip_ids:
                continue
            if item.get("required_for_startup") and item.get("status") not in RESOLVED_STATUSES:
                return item
        return None

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

    def _ensure_profile_defaults(self, profile: Dict[str, Any]) -> bool:
        changed = False
        if profile.get("active_mode") not in STARTUP_MODES:
            profile["active_mode"] = "startup"
            changed = True
        if int(profile.get("discretion_level", 2)) not in DISCRETION_LEVELS:
            profile["discretion_level"] = 2
            changed = True
        if "freeform_notes" not in profile:
            profile["freeform_notes"] = []
            changed = True
        default_by_id = {item["question_id"]: item for item in DEFAULT_STARTUP_DIMENSIONS}
        for item in profile.get("dimensions", []):
            normalized = normalize_question_id(str(item.get("question_id", "")))
            default = default_by_id.get(normalized)
            if default is None:
                continue
            for key, value in default.items():
                if key not in item:
                    item[key] = value
                    changed = True
            if item.get("question_id") != default["question_id"]:
                item["question_id"] = default["question_id"]
                changed = True
            if "selected_choice" not in item:
                item["selected_choice"] = None
                changed = True
        if changed:
            profile["updated_at"] = utc_now()
        return changed

    def _validate_mode(self, mode: str) -> str:
        if mode not in STARTUP_MODES:
            raise ValueError(f"unsupported startup mode: {mode}")
        return mode

    def _normalize_choice(self, choice: str | None) -> str | None:
        if choice is None:
            return None
        normalized = choice.lower().strip()
        if normalized not in "abcdefghi":
            raise ValueError("choice must be one of a-i")
        return normalized


def normalize_question_id(question_id: str) -> str:
    value = question_id.strip().upper()
    if value.startswith("Q"):
        value = value[1:]
    if not value.isdigit():
        return question_id
    return f"{int(value):04d}"


def parse_startup_answer_text(text: str) -> Tuple[List[Tuple[str, str]], str]:
    selections: List[Tuple[str, str]] = []
    seen = set()
    for match in ANSWER_CODE_PATTERN.finditer(text):
        question_id = f"{int(match.group(1)):04d}"
        choice = match.group(2).lower()
        if question_id not in seen:
            selections.append((question_id, choice))
            seen.add(question_id)
    note = ANSWER_CODE_PATTERN.sub(" ", text)
    note = " ".join(note.split())
    return selections, note


def choice_labels_for_question(item: Dict[str, Any], mode: str) -> List[Dict[str, str]]:
    source_key = "easypicks" if mode == "easystartup" else "startup_choices"
    choices = item.get(source_key) or []
    return [
        {
            "label": chr(ord("a") + index),
            "code": f"{item['question_id']}{chr(ord('a') + index)}",
            "text": str(choice),
        }
        for index, choice in enumerate(choices[:9])
    ]


def startup_status_to_dict(status: StartupStatus) -> Dict[str, Any]:
    return {
        "startup_ambiguity_percent": status.startup_ambiguity_percent,
        "interview_progress_percent": status.progress_percent,
        "interview_remaining_percent": status.remaining_percent,
        "required_resolved": status.required_resolved,
        "required_total": status.required_total,
        "startup_ready": status.startup_ready,
        "active_mode": status.active_mode,
        "discretion_level": status.discretion_level,
        "discretion_label": status.discretion_label,
        "profile_path": str(status.profile_path),
    }


def startup_interview_to_dict(round_: StartupInterviewRound) -> Dict[str, Any]:
    questions = []
    for item in round_.questions:
        prompt_key = (
            "easystartup_prompt" if round_.mode == "easystartup" else "startup_prompt"
        )
        questions.append(
            {
                "question_id": item["question_id"],
                "legacy_question_id": item.get("legacy_question_id"),
                "status": item["status"],
                "dimension": item["dimension"],
                "prompt": item[prompt_key],
                "choices": choice_labels_for_question(item, round_.mode),
                "free_text": round_.mode == "startup",
                "agent_fill": round_.mode == "easystartup",
            }
        )
    next_question = None
    if round_.next_question is not None:
        prompt_key = (
            "easystartup_prompt" if round_.mode == "easystartup" else "startup_prompt"
        )
        next_question = {
            "question_id": round_.next_question["question_id"],
            "legacy_question_id": round_.next_question.get("legacy_question_id"),
            "dimension": round_.next_question["dimension"],
            "prompt": round_.next_question[prompt_key],
            "choices": choice_labels_for_question(round_.next_question, round_.mode),
        }
    return {
        "round_id": round_.round_id,
        "mode": round_.mode,
        "startup_ambiguity_before_percent": round_.ambiguity_before,
        "interview_progress_before_percent": round_.progress_before,
        "interview_remaining_after_percent": round_.remaining_after,
        "question_budget": round_.question_budget,
        "discretion_level": round_.discretion_level,
        "discretion_label": round_.discretion_label,
        "answer_format": "0001a 0002b 0003e plus optional free text",
        "questions": questions,
        "next_question": next_question,
        "meeting_buckets": round_.meeting_buckets,
    }


def format_startup_status(status: StartupStatus) -> List[str]:
    return [
        f"startup_ambiguity: {status.startup_ambiguity_percent}%",
        f"interview_progress: {status.progress_percent}%",
        f"interview_remaining: {status.remaining_percent}%",
        f"required_resolved: {status.required_resolved}/{status.required_total}",
        f"startup_ready: {'yes' if status.startup_ready else 'no'}",
        f"active_mode: {status.active_mode}",
        f"discretion_level: {status.discretion_level} ({status.discretion_label})",
        f"profile_path: {status.profile_path}",
    ]


def format_startup_interview(round_: StartupInterviewRound) -> List[str]:
    lines = [
        f"startup_interview_round: {round_.round_id}",
        f"startup_interview_mode: {round_.mode}",
        f"startup_ambiguity_before: {round_.ambiguity_before}%",
        f"interview_progress: {round_.progress_before}%",
        f"interview_remaining: {round_.remaining_after}%",
        f"question_budget: {round_.question_budget}",
        f"discretion_level: {round_.discretion_level} ({round_.discretion_label})",
        "answer_format: 0001a 0002b 0003e plus optional free text",
        "required_for_startup:",
    ]
    for item in round_.questions:
        prompt = item["easystartup_prompt"] if round_.mode == "easystartup" else item["startup_prompt"]
        lines.append(
            "\t".join(
                [
                    item["question_id"],
                    item["status"],
                    item["dimension"],
                    prompt,
                ]
            )
        )
        choices = choice_labels_for_question(item, round_.mode)
        lines.append(
            "choices: "
            + " | ".join(f"{choice['code']}={choice['text']}" for choice in choices)
        )
        if round_.mode == "startup":
            lines.append("free_text: long-form author answer encouraged")
        else:
            lines.append("agent_fill: Hermes may fill details according to discretion_level")
    if round_.next_question is not None:
        lines.append(
            "next_question: "
            + "\t".join(
                [
                    round_.next_question["question_id"],
                    round_.next_question["dimension"],
                ]
            )
        )
    else:
        lines.append("next_question: none")
    lines.append("deferred_to_meeting:")
    lines.extend(
        "\t".join([item["bucket_id"], item["topic"], item["prompt"]])
        for item in round_.meeting_buckets
    )
    return lines
