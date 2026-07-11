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
STARTUP_DEFAULTS_REVISION = 2
STARTUP_QUESTION_PACK_ID = "public_neutral_v2"
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

MINIMUM_FRAME_QUESTION_IDS = frozenset({"0001", "0002", "0003", "0004"})
STARTUP_DIMENSION_ROLES = {
    "creation_goal": "project_intent",
    "starting_material": "project_intent",
    "author_control": "workflow_preference",
    "output_target": "workflow_preference",
    "reality_distance": "world_assertion",
    "tone_experience": "world_assertion",
    "scope_focus": "world_assertion",
    "change_pressure": "world_assertion",
    "known_vs_unknown": "workflow_preference",
    "boundaries_and_preferences": "workflow_preference",
}
LEGACY_WORLD_ASSERTION_DIMENSIONS = frozenset(
    item
    for item in (
        "premise_genre_tone",
        "era_daily_life",
        "power_access_limits",
        "core_institutions",
        "conflict_engine",
        "pov_anchor",
        "first_stage_geography",
        "social_economic_baseline",
        "hidden_truth_reveal_policy",
        "opening_incident",
    )
)
SEMANTIC_EXPLICIT = "explicit"
SEMANTIC_DEFERRED = "deferred_unknown"

# Values are stable meanings; displayed choice labels remain independently editable.
STARTUP_CHOICE_SEMANTICS: Dict[
    str, Dict[str, List[Tuple[str, str]]]
] = {
    "creation_goal": {
        "startup": [
            ("new_narrative_project", SEMANTIC_EXPLICIT),
            ("interactive_setting_project", SEMANTIC_EXPLICIT),
            ("organize_existing_world_material", SEMANTIC_EXPLICIT),
        ],
        "easystartup": [
            ("story_or_novel", SEMANTIC_EXPLICIT),
            ("game_or_interactive_project", SEMANTIC_EXPLICIT),
            ("tabletop_or_roleplay_setting", SEMANTIC_EXPLICIT),
            ("world_reference_or_setting_bible", SEMANTIC_EXPLICIT),
            ("organize_existing_material", SEMANTIC_EXPLICIT),
            ("creation_goal_undecided", SEMANTIC_DEFERRED),
        ],
    },
    "starting_material": {
        "startup": [
            ("blank_or_short_idea", SEMANTIC_EXPLICIT),
            ("known_world_element", SEMANTIC_EXPLICIT),
            ("existing_draft_notes_or_data", SEMANTIC_EXPLICIT),
        ],
        "easystartup": [
            ("blank_workspace", SEMANTIC_EXPLICIT),
            ("one_sentence_idea", SEMANTIC_EXPLICIT),
            ("known_character", SEMANTIC_EXPLICIT),
            ("known_place_or_situation", SEMANTIC_EXPLICIT),
            ("known_rule_or_constraint", SEMANTIC_EXPLICIT),
            ("existing_draft_or_notes", SEMANTIC_EXPLICIT),
        ],
    },
    "author_control": {
        "startup": [
            ("questions_only", SEMANTIC_EXPLICIT),
            ("bounded_alternatives", SEMANTIC_EXPLICIT),
            ("bounded_draft_until_checkpoint", SEMANTIC_EXPLICIT),
        ],
        "easystartup": [
            ("questions_only", SEMANTIC_EXPLICIT),
            ("neutral_options_only", SEMANTIC_EXPLICIT),
            ("small_gap_candidates", SEMANTIC_EXPLICIT),
            ("contrasting_candidates", SEMANTIC_EXPLICIT),
            ("bounded_draft_until_checkpoint", SEMANTIC_EXPLICIT),
            ("author_control_undecided", SEMANTIC_DEFERRED),
        ],
    },
    "output_target": {
        "startup": [
            ("question_list_and_decision_log", SEMANTIC_EXPLICIT),
            ("world_outline_or_rules_summary", SEMANTIC_EXPLICIT),
            ("reviewable_world_candidates", SEMANTIC_EXPLICIT),
        ],
        "easystartup": [
            ("question_list", SEMANTIC_EXPLICIT),
            ("world_outline", SEMANTIC_EXPLICIT),
            ("rules_and_constraints_summary", SEMANTIC_EXPLICIT),
            ("character_candidates", SEMANTIC_EXPLICIT),
            ("place_or_situation_candidates", SEMANTIC_EXPLICIT),
            ("first_scene_candidates", SEMANTIC_EXPLICIT),
        ],
    },
    "reality_distance": {
        "startup": [
            ("close_to_known_reality", SEMANTIC_EXPLICIT),
            ("fully_invented_frame", SEMANTIC_EXPLICIT),
            ("reality_distance_undecided", SEMANTIC_DEFERRED),
        ],
        "easystartup": [
            ("close_to_present_reality", SEMANTIC_EXPLICIT),
            ("historically_grounded", SEMANTIC_EXPLICIT),
            ("future_or_technology_shifted", SEMANTIC_EXPLICIT),
            ("fully_invented", SEMANTIC_EXPLICIT),
            ("surreal_or_symbolic", SEMANTIC_EXPLICIT),
            ("reality_distance_undecided", SEMANTIC_DEFERRED),
        ],
    },
    "tone_experience": {
        "startup": [
            ("warm_reflective_relationship_focused", SEMANTIC_EXPLICIT),
            ("serious_tense_demanding", SEMANTIC_EXPLICIT),
            ("adventurous_playful_exploratory", SEMANTIC_EXPLICIT),
        ],
        "easystartup": [
            ("warm", SEMANTIC_EXPLICIT),
            ("serious", SEMANTIC_EXPLICIT),
            ("adventurous", SEMANTIC_EXPLICIT),
            ("comic", SEMANTIC_EXPLICIT),
            ("tense", SEMANTIC_EXPLICIT),
            ("tone_undecided", SEMANTIC_DEFERRED),
        ],
    },
    "scope_focus": {
        "startup": [
            ("person_or_small_group", SEMANTIC_EXPLICIT),
            ("place_organization_or_community", SEMANTIC_EXPLICIT),
            ("region_society_or_larger_system", SEMANTIC_EXPLICIT),
        ],
        "easystartup": [
            ("one_person", SEMANTIC_EXPLICIT),
            ("small_group", SEMANTIC_EXPLICIT),
            ("one_place", SEMANTIC_EXPLICIT),
            ("organization_or_community", SEMANTIC_EXPLICIT),
            ("region_or_society", SEMANTIC_EXPLICIT),
            ("scope_undecided", SEMANTIC_DEFERRED),
        ],
    },
    "change_pressure": {
        "startup": [
            ("personal_or_relationship_change", SEMANTIC_EXPLICIT),
            ("external_constraint_or_resource_pressure", SEMANTIC_EXPLICIT),
            ("change_pressure_undecided", SEMANTIC_DEFERRED),
        ],
        "easystartup": [
            ("personal_need", SEMANTIC_EXPLICIT),
            ("relationship_change", SEMANTIC_EXPLICIT),
            ("external_event", SEMANTIC_EXPLICIT),
            ("change_pressure_unknown", SEMANTIC_DEFERRED),
            ("resource_or_time_pressure", SEMANTIC_EXPLICIT),
            ("no_central_pressure_yet", SEMANTIC_DEFERRED),
        ],
    },
    "known_vs_unknown": {
        "startup": [
            ("mostly_transparent", SEMANTIC_EXPLICIT),
            ("record_selected_unknowns", SEMANTIC_EXPLICIT),
            ("candidate_explanations_for_review", SEMANTIC_EXPLICIT),
        ],
        "easystartup": [
            ("mostly_transparent", SEMANTIC_EXPLICIT),
            ("few_open_questions", SEMANTIC_EXPLICIT),
            ("unknowns_recorded_without_answers", SEMANTIC_EXPLICIT),
            ("candidate_explanations", SEMANTIC_EXPLICIT),
            ("decide_during_later_scenes", SEMANTIC_EXPLICIT),
            ("unknown_handling_no_preference", SEMANTIC_DEFERRED),
        ],
    },
    "boundaries_and_preferences": {
        "startup": [
            ("record_avoidance_or_intensity_boundaries", SEMANTIC_EXPLICIT),
            ("record_required_audience_or_format_constraints", SEMANTIC_EXPLICIT),
            ("boundaries_deferred", SEMANTIC_DEFERRED),
        ],
        "easystartup": [
            ("avoidance_boundaries", SEMANTIC_EXPLICIT),
            ("intensity_limits", SEMANTIC_EXPLICIT),
            ("audience_constraints", SEMANTIC_EXPLICIT),
            ("required_elements", SEMANTIC_EXPLICIT),
            ("format_constraints", SEMANTIC_EXPLICIT),
            ("boundaries_deferred", SEMANTIC_DEFERRED),
        ],
    },
}


LEGACY_STARTUP_DIMENSIONS_V1 = [
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


DEFAULT_STARTUP_DIMENSIONS: List[Dict[str, Any]] = [
    {
        "question_id": "0001",
        "legacy_question_id": "Q001",
        "dimension": "creation_goal",
        "startup_prompt": "What are you trying to create or organize in this world workspace?",
        "startup_choices": [
            "Create a new narrative or story project.",
            "Prepare a game, role-play, or interactive setting.",
            "Organize or inspect existing world material.",
        ],
        "easystartup_prompt": "Choose the closest creation goal.",
        "easypicks": [
            "story or novel",
            "game or interactive project",
            "tabletop or role-play setting",
            "world reference or setting bible",
            "organize existing material",
            "not sure yet",
        ],
        "weight": 10,
    },
    {
        "question_id": "0002",
        "legacy_question_id": "Q002",
        "dimension": "starting_material",
        "startup_prompt": "What material already exists, if any?",
        "startup_choices": [
            "Start from a blank workspace or a short idea.",
            "Start from one known character, place, rule, or situation.",
            "Bring in an existing draft, notes, or structured data.",
        ],
        "easystartup_prompt": "Choose the closest starting point.",
        "easypicks": [
            "blank workspace",
            "one-sentence idea",
            "known character",
            "known place or situation",
            "known rule or constraint",
            "existing draft or notes",
        ],
        "weight": 10,
    },
    {
        "question_id": "0003",
        "legacy_question_id": "Q003",
        "dimension": "author_control",
        "startup_prompt": "How much should the system suggest before returning decisions to you?",
        "startup_choices": [
            "Ask questions only and do not fill gaps.",
            "Offer bounded alternatives for me to choose from.",
            "Draft candidate material until a stated review checkpoint.",
        ],
        "easystartup_prompt": "Choose the preferred suggestion level.",
        "easypicks": [
            "questions only",
            "neutral options only",
            "small gap candidates",
            "several contrasting candidates",
            "bounded draft until checkpoint",
            "decide later",
        ],
        "weight": 10,
    },
    {
        "question_id": "0004",
        "legacy_question_id": "Q004",
        "dimension": "output_target",
        "startup_prompt": "What useful output should this startup pass produce first?",
        "startup_choices": [
            "A clarified question list and decision log.",
            "A compact world outline or rules summary.",
            "Reviewable candidates for characters, places, or scenes.",
        ],
        "easystartup_prompt": "Choose the first useful output.",
        "easypicks": [
            "question list",
            "world outline",
            "rules and constraints summary",
            "character candidates",
            "place or situation candidates",
            "first scene candidates",
        ],
        "weight": 10,
    },
    {
        "question_id": "0005",
        "legacy_question_id": "Q005",
        "dimension": "reality_distance",
        "startup_prompt": "How closely should the world relate to known reality or history?",
        "startup_choices": [
            "Stay close to present or historical reality.",
            "Use a fully invented frame with its own assumptions.",
            "Mix familiar and invented elements without deciding the balance yet.",
        ],
        "easystartup_prompt": "Choose the closest reality distance.",
        "easypicks": [
            "close to present reality",
            "historically grounded",
            "future or technology-shifted",
            "fully invented",
            "surreal or symbolic",
            "hybrid or undecided",
        ],
        "weight": 10,
    },
    {
        "question_id": "0006",
        "legacy_question_id": "Q006",
        "dimension": "tone_experience",
        "startup_prompt": "What broad experience should the work create for its audience or players?",
        "startup_choices": [
            "Warm, reflective, or relationship-focused.",
            "Serious, tense, or demanding.",
            "Adventurous, playful, or exploratory.",
        ],
        "easystartup_prompt": "Choose the closest broad experience.",
        "easypicks": [
            "warm",
            "serious",
            "adventurous",
            "comic",
            "tense",
            "reflective or undecided",
        ],
        "weight": 10,
    },
    {
        "question_id": "0007",
        "legacy_question_id": "Q007",
        "dimension": "scope_focus",
        "startup_prompt": "What scale should receive attention first?",
        "startup_choices": [
            "One person or a small group.",
            "One place, organization, or community.",
            "A region, society, or larger system.",
        ],
        "easystartup_prompt": "Choose the initial scope.",
        "easypicks": [
            "one person",
            "small group",
            "one place",
            "organization or community",
            "region or society",
            "large scale or undecided",
        ],
        "weight": 10,
    },
    {
        "question_id": "0008",
        "legacy_question_id": "Q008",
        "dimension": "change_pressure",
        "startup_prompt": "What kind of change or pressure, if any, should be explored first?",
        "startup_choices": [
            "A personal need or relationship change.",
            "An external event, constraint, or resource pressure.",
            "Keep the initial state open before defining a central pressure.",
        ],
        "easystartup_prompt": "Choose the closest source of change.",
        "easypicks": [
            "personal need",
            "relationship change",
            "external event",
            "unknown situation",
            "resource or time pressure",
            "no central pressure yet",
        ],
        "weight": 10,
    },
    {
        "question_id": "0009",
        "legacy_question_id": "Q009",
        "dimension": "known_vs_unknown",
        "startup_prompt": "How should known information and unresolved questions be handled?",
        "startup_choices": [
            "Keep the initial world mostly transparent.",
            "Record selected unknowns without inventing answers yet.",
            "Allow several candidate explanations for later review.",
        ],
        "easystartup_prompt": "Choose how unresolved information should be handled.",
        "easypicks": [
            "mostly transparent",
            "a few open questions",
            "unknowns recorded without answers",
            "candidate explanations",
            "decide during later scenes",
            "no preference yet",
        ],
        "weight": 10,
    },
    {
        "question_id": "0010",
        "legacy_question_id": "Q010",
        "dimension": "boundaries_and_preferences",
        "startup_prompt": "What boundaries, required elements, or audience constraints should guide later work?",
        "startup_choices": [
            "Record material or intensity to avoid.",
            "Record required themes, audience needs, or format constraints.",
            "Leave boundaries open and return to them before generation.",
        ],
        "easystartup_prompt": "Choose what to record about boundaries now.",
        "easypicks": [
            "avoidance boundaries",
            "intensity limits",
            "audience constraints",
            "required elements",
            "format constraints",
            "review later",
        ],
        "weight": 10,
    },
]

for _default_dimension in DEFAULT_STARTUP_DIMENSIONS:
    _default_dimension["answer_role"] = STARTUP_DIMENSION_ROLES[
        _default_dimension["dimension"]
    ]
    _default_dimension["required_for_minimum_frame"] = (
        _default_dimension["question_id"] in MINIMUM_FRAME_QUESTION_IDS
    )
del _default_dimension


LEGACY_MEETING_BUCKETS_V1 = [
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


DEFAULT_MEETING_BUCKETS = [
    {
        "bucket_id": "M001",
        "topic": "intent_and_constraints",
        "prompt": "Summarize the user's stated goal, source material, boundaries, and unresolved decisions without inventing world facts.",
    },
    {
        "bucket_id": "M002",
        "topic": "candidate_directions",
        "prompt": "Draft a small set of clearly labeled, contrasting candidate directions grounded only in startup answers.",
    },
    {
        "bucket_id": "M003",
        "topic": "next_artifact",
        "prompt": "Recommend the next reviewable artifact or question set and state what remains unknown.",
    },
]


@dataclass(frozen=True)
class StartupStatus:
    startup_ambiguity_percent: int
    progress_percent: int
    remaining_percent: int
    required_total: int
    required_resolved: int
    minimum_frame_total: int
    minimum_frame_resolved: int
    minimum_frame_ready: bool
    full_interview_complete: bool
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
            "defaults_revision": STARTUP_DEFAULTS_REVISION,
            "question_pack_id": STARTUP_QUESTION_PACK_ID,
            "question_pack_contract": _question_pack_contract(
                STARTUP_QUESTION_PACK_ID
            ),
            "readiness_policy": _readiness_policy(),
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
                    "style": "neutral_frame_first_easy_pick",
                    "choice_count": "5_to_8",
                    "agent_detail_fill": "candidate_suggestions_after_user_frame",
                },
            },
            "generation_policy": {
                "autonomy_owner": "user_hermes_runtime_dialogue",
                "autonomy_range": {"min": 0, "max": 100},
                "discretion_customizable": True,
                "discretion_scale": discretion_scale_contract(),
                "fill_the_rest": fill_the_rest_contract(),
                "fully_autonomous_generation_allowed": False,
                "external_runtime_policy_required_for_autonomous_generation": True,
                "checkpoint_style": "natural_language_recommended",
                "checkpoint_examples": [
                    "until the requested outline is ready for review",
                    "until three contrasting candidates are available",
                    "until the user-defined review condition is met",
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

    def summary(self, mode: str | None = None) -> Dict[str, Any]:
        profile = self.load_or_create()
        status = self._status(
            profile,
            active_mode=self._validate_mode(mode) if mode is not None else None,
        )
        answers: List[Dict[str, Any]] = []
        project_intent: List[Dict[str, Any]] = []
        workflow_preferences: List[Dict[str, Any]] = []
        explicit_world_assertions: List[Dict[str, Any]] = []
        unresolved: List[Dict[str, Any]] = []
        unresolved_blockers: List[Dict[str, Any]] = []
        optional_unknowns: List[Dict[str, Any]] = []
        for item in profile.get("dimensions", []):
            if item.get("status") in RESOLVED_STATUSES:
                answer = _startup_answer_record(profile, item)
                answers.append(answer)
                if answer["semantic_state"] == SEMANTIC_DEFERRED:
                    deferred = {
                        **answer,
                        "state": "explicitly_deferred",
                        "reason": "selected_meaning_does_not_resolve_the_dimension",
                    }
                    if _requires_minimum_frame(item):
                        unresolved_blockers.append(deferred)
                    else:
                        optional_unknowns.append(deferred)
                elif answer["answer_role"] == "project_intent":
                    project_intent.append(answer)
                elif answer["answer_role"] == "workflow_preference":
                    workflow_preferences.append(answer)
                elif answer["answer_role"] == "world_assertion":
                    explicit_world_assertions.append(answer)
                continue

            gap = _startup_gap_record(item)
            if item.get("required_for_startup"):
                unresolved.append(
                    {
                        "question_id": gap["question_id"],
                        "dimension": gap["dimension"],
                    }
                )
            if _requires_minimum_frame(item):
                unresolved_blockers.append(gap)
            else:
                optional_unknowns.append(gap)

        readiness = {
            "minimum_frame_ready": status.minimum_frame_ready,
            "minimum_frame_resolved": status.minimum_frame_resolved,
            "minimum_frame_total": status.minimum_frame_total,
            "full_interview_complete": status.full_interview_complete,
            "interview_resolved": status.required_resolved,
            "interview_total": status.required_total,
            "interview_progress_percent": status.progress_percent,
        }
        if unresolved_blockers:
            next_actions = ["continue_startup_interview"]
        elif not status.full_interview_complete:
            next_actions = [
                "review_minimum_startup_frame",
                "continue_optional_startup_interview",
                "prepare_proposal_preview_after_review",
            ]
        else:
            next_actions = [
                "review_startup_summary",
                "prepare_proposal_preview_after_review",
            ]
        outcome = {
            "schema": "wsa.world_startup.outcome.v1",
            "readiness": readiness,
            "project_intent": project_intent,
            "workflow_preferences": workflow_preferences,
            "explicit_world_assertions": explicit_world_assertions,
            "unresolved_blockers": unresolved_blockers,
            "optional_unknowns": optional_unknowns,
        }
        return {
            "schema": "wsa.world_startup.summary.v1",
            "world_id": self.world.world_id,
            "question_pack_id": profile.get("question_pack_id"),
            "question_pack_contract": dict(profile.get("question_pack_contract") or {}),
            "defaults_revision": profile.get("defaults_revision"),
            "active_mode": status.active_mode,
            "startup_ready": status.startup_ready,
            "minimum_frame_ready": status.minimum_frame_ready,
            "full_interview_complete": status.full_interview_complete,
            "readiness": readiness,
            "project_intent": project_intent,
            "workflow_preferences": workflow_preferences,
            "explicit_world_assertions": explicit_world_assertions,
            "unresolved_blockers": unresolved_blockers,
            "optional_unknowns": optional_unknowns,
            "outcome": outcome,
            "interview_progress_percent": status.progress_percent,
            "answers": answers,
            "unresolved": unresolved,
            "freeform_notes": list(profile.get("freeform_notes", [])),
            "next_actions": next_actions,
            "side_effect_status": "read_only_summary_no_world_mutation",
        }

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
        selected_option = None
        if selected_choice is not None:
            selected_option = self._choice(item, active_mode, selected_choice)
        now = utc_now()
        item["answer"] = text.strip()
        item["selected_choice"] = selected_choice
        item["answered_by"] = answered_by
        item["status"] = "answered_by_author" if answered_by == "author" else "proposed_by_agent"
        item["approved_by_author"] = answered_by == "author"
        item["updated_at"] = now
        self._record_answer_metadata(
            profile,
            item,
            active_mode,
            answered_by,
            selected_option,
            now,
        )
        profile["updated_at"] = now
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
            option = self._choice(item, active_mode, choice)
            now = utc_now()
            item["answer"] = f"{choice}) {option['choice_label']}"
            item["selected_choice"] = choice
            item["answered_by"] = answered_by
            item["status"] = "answered_by_author" if answered_by == "author" else "proposed_by_agent"
            item["approved_by_author"] = answered_by == "author"
            item["updated_at"] = now
            self._record_answer_metadata(
                profile,
                item,
                active_mode,
                answered_by,
                option,
                now,
            )
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
        now = utc_now()
        item["status"] = status
        item["approved_by_author"] = status == "approved_by_author"
        if status == "approved_by_author":
            item["author_approval"] = {
                "approved": True,
                "approved_at": now,
            }
        item["updated_at"] = now
        profile["updated_at"] = now
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
        minimum_frame = [item for item in profile["dimensions"] if _requires_minimum_frame(item)]
        total_weight = sum(int(item["weight"]) for item in required)
        unresolved_weight = sum(
            int(item["weight"])
            for item in required
            if item.get("status") not in RESOLVED_STATUSES
        )
        resolved_count = sum(1 for item in required if item.get("status") in RESOLVED_STATUSES)
        minimum_frame_resolved = sum(
            1
            for item in minimum_frame
            if item.get("status") in RESOLVED_STATUSES
            and _semantic_state_for_item(item) != SEMANTIC_DEFERRED
        )
        ambiguity = int(round((unresolved_weight / total_weight) * 100)) if total_weight else 0
        progress = 100 - ambiguity
        minimum_frame_ready = minimum_frame_resolved == len(minimum_frame)
        full_interview_complete = ambiguity == 0
        discretion_level = int(profile.get("discretion_level", 2))
        return StartupStatus(
            startup_ambiguity_percent=ambiguity,
            progress_percent=progress,
            remaining_percent=ambiguity,
            required_total=len(required),
            required_resolved=resolved_count,
            minimum_frame_total=len(minimum_frame),
            minimum_frame_resolved=minimum_frame_resolved,
            minimum_frame_ready=minimum_frame_ready,
            full_interview_complete=full_interview_complete,
            startup_ready=minimum_frame_ready,
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
        return str(self._choice(item, mode, choice)["choice_label"])

    def _choice(
        self,
        item: Dict[str, Any],
        mode: str,
        choice: str,
    ) -> Dict[str, Any]:
        choices = choice_labels_for_question(item, mode)
        for option in choices:
            if option["label"] == choice:
                return option
        raise ValueError(f"choice {choice} is not available for {item['question_id']}")

    def _record_answer_metadata(
        self,
        profile: Dict[str, Any],
        item: Dict[str, Any],
        mode: str,
        answered_by: str,
        selected_option: Dict[str, Any] | None,
        recorded_at: str,
    ) -> None:
        if selected_option is None:
            semantic_value = str(item.get("answer") or "").strip()
            semantic_state = _free_text_semantic_state(semantic_value)
            choice_code = None
            choice_label = None
            source_kind = "free_text"
        else:
            semantic_value = selected_option["semantic_value"]
            semantic_state = selected_option["semantic_state"]
            choice_code = selected_option["choice_code"]
            choice_label = selected_option["choice_label"]
            source_kind = "ui_choice"
        item["selected_choice_code"] = choice_code
        item["selected_choice_label"] = choice_label
        item["semantic_value"] = semantic_value
        item["semantic_state"] = semantic_state
        item["answer_mode"] = mode
        item["answer_source"] = {
            "kind": source_kind,
            "source_ref": "startup/startup_profile.json",
            "question_pack_id": profile.get("question_pack_id"),
            "defaults_revision": profile.get("defaults_revision"),
            "mode": mode,
        }
        item["answer_provenance"] = {
            "answered_by": answered_by,
            "origin": _answer_origin(answered_by),
            "recorded_at": recorded_at,
        }

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
        previous_revision = int(profile.get("defaults_revision", 1))
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
        legacy_by_id = {
            item["question_id"]: item for item in LEGACY_STARTUP_DIMENSIONS_V1
        }
        mixed_legacy = False
        for item in profile.get("dimensions", []):
            normalized = normalize_question_id(str(item.get("question_id", "")))
            default = default_by_id.get(normalized)
            if default is None:
                continue
            legacy = legacy_by_id.get(normalized)
            if previous_revision < STARTUP_DEFAULTS_REVISION and legacy is not None:
                if item.get("status") in RESOLVED_STATUSES or str(item.get("answer") or "").strip():
                    item["legacy_preserved"] = True
                    item["legacy_defaults_revision"] = 1
                    mixed_legacy = True
                    changed = True
                    continue
                if _matches_default_question(item, legacy):
                    for key, value in default.items():
                        item[key] = value
                    item["migrated_from_defaults_revision"] = 1
                    changed = True
                else:
                    item["legacy_preserved"] = True
                    item["legacy_defaults_revision"] = 1
                    mixed_legacy = True
                    changed = True
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
        existing_ids = {
            normalize_question_id(str(item.get("question_id", "")))
            for item in profile.get("dimensions", [])
        }
        for default in DEFAULT_STARTUP_DIMENSIONS:
            if default["question_id"] in existing_ids:
                continue
            profile.setdefault("dimensions", []).append(
                {
                    **default,
                    "required_for_startup": True,
                    "status": "unasked",
                    "answer": None,
                    "selected_choice": None,
                    "answered_by": None,
                    "approved_by_author": False,
                    "updated_at": None,
                }
            )
            changed = True
        if previous_revision < STARTUP_DEFAULTS_REVISION:
            if profile.get("meeting_buckets") == LEGACY_MEETING_BUCKETS_V1:
                profile["meeting_buckets"] = DEFAULT_MEETING_BUCKETS
            policy = profile.setdefault("interview_policy", {})
            easy = policy.setdefault("easystartup", {})
            easy["style"] = "neutral_frame_first_easy_pick"
            easy["agent_detail_fill"] = "candidate_suggestions_after_user_frame"
            generation = profile.setdefault("generation_policy", {})
            generation["fully_autonomous_generation_allowed"] = False
            generation["external_runtime_policy_required_for_autonomous_generation"] = True
            generation["checkpoint_examples"] = [
                "until the requested outline is ready for review",
                "until three contrasting candidates are available",
                "until the user-defined review condition is met",
            ]
            profile["defaults_revision"] = STARTUP_DEFAULTS_REVISION
            profile["question_pack_id"] = (
                "mixed_legacy_preserved_v2" if mixed_legacy else STARTUP_QUESTION_PACK_ID
            )
            changed = True
        elif not profile.get("question_pack_id"):
            profile["question_pack_id"] = STARTUP_QUESTION_PACK_ID
            changed = True

        question_pack_contract = _question_pack_contract(
            str(profile.get("question_pack_id") or STARTUP_QUESTION_PACK_ID)
        )
        current_pack_contract = profile.get("question_pack_contract")
        if not isinstance(current_pack_contract, dict):
            profile["question_pack_contract"] = question_pack_contract
            changed = True
        else:
            for key, value in question_pack_contract.items():
                if key not in current_pack_contract:
                    current_pack_contract[key] = value
                    changed = True

        readiness_policy = _readiness_policy()
        current_readiness_policy = profile.get("readiness_policy")
        if not isinstance(current_readiness_policy, dict):
            profile["readiness_policy"] = readiness_policy
            changed = True
        else:
            for key, value in readiness_policy.items():
                if key not in current_readiness_policy:
                    current_readiness_policy[key] = value
                    changed = True

        for item in profile.get("dimensions", []):
            if "answer_role" not in item:
                item["answer_role"] = _answer_role_for_item(item)
                changed = True
            if "required_for_minimum_frame" not in item:
                item["required_for_minimum_frame"] = (
                    normalize_question_id(str(item.get("question_id", "")))
                    in MINIMUM_FRAME_QUESTION_IDS
                )
                changed = True
            if _ensure_answer_metadata(profile, item):
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


def _matches_default_question(item: Dict[str, Any], default: Dict[str, Any]) -> bool:
    keys = (
        "dimension",
        "startup_prompt",
        "startup_choices",
        "easystartup_prompt",
        "easypicks",
        "weight",
    )
    return all(item.get(key) == default.get(key) for key in keys)


def _question_pack_contract(question_pack_id: str) -> Dict[str, Any]:
    return {
        "schema": "wsa.world_startup.question_pack_contract.v1",
        "question_pack_id": question_pack_id,
        "pack_type": (
            "fixed_neutral"
            if question_pack_id == STARTUP_QUESTION_PACK_ID
            else "profile_preserved"
        ),
        "selection_policy": "static_profile_and_in_process_defaults_only",
        "memory_inputs": [],
        "excluded_memory_inputs": [
            "beta_memory",
            "user_memory",
            "manager_memory",
        ],
        "reads_beta_memory": False,
        "reads_user_memory": False,
        "reads_manager_memory": False,
    }


def _readiness_policy() -> Dict[str, Any]:
    return {
        "schema": "wsa.world_startup.readiness_policy.v1",
        "minimum_frame_question_ids": sorted(MINIMUM_FRAME_QUESTION_IDS),
        "full_interview_question_ids": [
            item["question_id"] for item in DEFAULT_STARTUP_DIMENSIONS
        ],
        "deferred_choice_counts_as_interview_answer": True,
        "deferred_choice_satisfies_minimum_frame": False,
    }


def _answer_role_for_item(item: Dict[str, Any]) -> str:
    dimension = str(item.get("dimension") or "")
    if dimension in STARTUP_DIMENSION_ROLES:
        return STARTUP_DIMENSION_ROLES[dimension]
    if dimension in LEGACY_WORLD_ASSERTION_DIMENSIONS:
        return "world_assertion"
    return "workflow_preference"


def _requires_minimum_frame(item: Dict[str, Any]) -> bool:
    configured = item.get("required_for_minimum_frame")
    if isinstance(configured, bool):
        return configured
    return (
        normalize_question_id(str(item.get("question_id") or ""))
        in MINIMUM_FRAME_QUESTION_IDS
    )


def _semantic_slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug or fallback


def _choice_semantic(
    item: Dict[str, Any],
    mode: str,
    index: int,
    choice_label: str,
) -> Tuple[str, str]:
    dimension = str(item.get("dimension") or "")
    contract = STARTUP_CHOICE_SEMANTICS.get(dimension, {}).get(mode, [])
    default = next(
        (
            candidate
            for candidate in DEFAULT_STARTUP_DIMENSIONS
            if candidate["dimension"] == dimension
        ),
        None,
    )
    source_key = "easypicks" if mode == "easystartup" else "startup_choices"
    default_choices = list(default.get(source_key) or []) if default else []
    if (
        index < len(contract)
        and index < len(default_choices)
        and str(default_choices[index]) == choice_label
    ):
        return contract[index]
    fallback = f"{normalize_question_id(str(item.get('question_id') or ''))}_{index + 1}"
    return _semantic_slug(choice_label, fallback), SEMANTIC_EXPLICIT


def _free_text_semantic_state(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9가-힣]+", " ", value.casefold()).strip()
    deferred_values = {
        "undecided",
        "undecided for now",
        "not sure",
        "not sure yet",
        "no preference",
        "no preference yet",
        "decide later",
        "leave open",
        "review later",
        "아직 미정",
        "미정",
        "나중에 결정",
    }
    return SEMANTIC_DEFERRED if normalized in deferred_values else SEMANTIC_EXPLICIT


def _semantic_state_for_item(item: Dict[str, Any]) -> str:
    value = item.get("semantic_state")
    if value in {SEMANTIC_EXPLICIT, SEMANTIC_DEFERRED}:
        return str(value)
    return _free_text_semantic_state(str(item.get("answer") or ""))


def _answer_origin(answered_by: str) -> str:
    if answered_by == "author":
        return "author_direct"
    if "agent" in answered_by:
        return "agent_proposal"
    return answered_by or "unknown"


def _infer_answer_mode(profile: Dict[str, Any], item: Dict[str, Any]) -> str:
    stored = item.get("answer_mode")
    if stored in STARTUP_MODES:
        return str(stored)
    selected = str(item.get("selected_choice") or "").lower()
    answer = str(item.get("answer") or "").casefold()
    if selected:
        for mode in ("startup", "easystartup"):
            for option in choice_labels_for_question(item, mode):
                if option["label"] != selected:
                    continue
                if str(option["choice_label"]).casefold() in answer:
                    return mode
    active_mode = str(profile.get("active_mode") or "startup")
    return active_mode if active_mode in STARTUP_MODES else "startup"


def _ensure_answer_metadata(profile: Dict[str, Any], item: Dict[str, Any]) -> bool:
    if not str(item.get("answer") or "").strip():
        return False
    changed = False
    mode = _infer_answer_mode(profile, item)
    selected = str(item.get("selected_choice") or "").lower()
    option = None
    if selected:
        option = next(
            (
                candidate
                for candidate in choice_labels_for_question(item, mode)
                if candidate["label"] == selected
            ),
            None,
        )
    values: Dict[str, Any]
    if option is None:
        answer = str(item.get("answer") or "").strip()
        values = {
            "selected_choice_code": None,
            "selected_choice_label": None,
            "semantic_value": answer,
            "semantic_state": _free_text_semantic_state(answer),
        }
        source_kind = "free_text"
    else:
        values = {
            "selected_choice_code": option["choice_code"],
            "selected_choice_label": option["choice_label"],
            "semantic_value": option["semantic_value"],
            "semantic_state": option["semantic_state"],
        }
        source_kind = "ui_choice"
    values["answer_mode"] = mode
    for key, value in values.items():
        if key not in item:
            item[key] = value
            changed = True

    source = item.get("answer_source")
    expected_source = {
        "kind": source_kind,
        "source_ref": "startup/startup_profile.json",
        "question_pack_id": profile.get("question_pack_id"),
        "defaults_revision": profile.get("defaults_revision"),
        "mode": mode,
    }
    if not isinstance(source, dict):
        item["answer_source"] = expected_source
        changed = True
    else:
        for key, value in expected_source.items():
            if key not in source:
                source[key] = value
                changed = True

    provenance = item.get("answer_provenance")
    answered_by = str(item.get("answered_by") or "unknown")
    expected_provenance = {
        "answered_by": answered_by,
        "origin": _answer_origin(answered_by),
        "recorded_at": item.get("updated_at"),
    }
    if not isinstance(provenance, dict):
        item["answer_provenance"] = expected_provenance
        changed = True
    else:
        for key, value in expected_provenance.items():
            if key not in provenance:
                provenance[key] = value
                changed = True
    return changed


def _startup_answer_record(
    profile: Dict[str, Any],
    item: Dict[str, Any],
) -> Dict[str, Any]:
    source = dict(item.get("answer_source") or {})
    provenance = dict(item.get("answer_provenance") or {})
    answered_by = str(item.get("answered_by") or provenance.get("answered_by") or "unknown")
    status = str(item.get("status") or "")
    origin = str(provenance.get("origin") or _answer_origin(answered_by))
    if origin == "author_direct":
        authority = "user_explicit"
    elif status == "approved_by_author":
        authority = "author_approved_agent_proposal"
    else:
        authority = origin
    provenance.update(
        {
            "answered_by": answered_by,
            "origin": origin,
            "answer_status": status,
            "approved_by_author": bool(item.get("approved_by_author")),
            "authority": authority,
            "legacy_preserved": bool(item.get("legacy_preserved")),
        }
    )
    source.setdefault("source_ref", "startup/startup_profile.json")
    source.setdefault("question_pack_id", profile.get("question_pack_id"))
    source.setdefault("defaults_revision", profile.get("defaults_revision"))
    choice_code = item.get("selected_choice_code")
    choice_label = item.get("selected_choice_label")
    semantic_value = item.get("semantic_value", item.get("answer"))
    choice = None
    if choice_code:
        choice = {
            "code": choice_code,
            "label": choice_label,
            "semantic_value": semantic_value,
        }
    role = _answer_role_for_item(item)
    semantic_state = _semantic_state_for_item(item)
    return {
        "question_id": item.get("question_id"),
        "dimension": item.get("dimension"),
        "answer_role": role,
        "classification": role,
        "answer": item.get("answer"),
        "selected_choice": item.get("selected_choice"),
        "choice_code": choice_code,
        "choice_label": choice_label,
        "semantic_value": semantic_value,
        "semantic_state": semantic_state,
        "choice": choice,
        "source": source,
        "provenance": provenance,
        "answered_by": answered_by,
        "status": status,
        "legacy_preserved": bool(item.get("legacy_preserved")),
        "canon_eligible": role == "world_assertion"
        and semantic_state == SEMANTIC_EXPLICIT,
    }


def _startup_gap_record(item: Dict[str, Any]) -> Dict[str, Any]:
    status = str(item.get("status") or "unasked")
    state = "pending_author_approval" if status == "proposed_by_agent" else status
    return {
        "question_id": item.get("question_id"),
        "dimension": item.get("dimension"),
        "answer_role": _answer_role_for_item(item),
        "status": status,
        "state": state,
        "required_for_minimum_frame": _requires_minimum_frame(item),
    }


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


def choice_labels_for_question(item: Dict[str, Any], mode: str) -> List[Dict[str, Any]]:
    source_key = "easypicks" if mode == "easystartup" else "startup_choices"
    choices = item.get(source_key) or []
    result = []
    for index, choice in enumerate(choices[:9]):
        choice_key = chr(ord("a") + index)
        choice_code = f"{item['question_id']}{choice_key}"
        choice_label = str(choice)
        semantic_value, semantic_state = _choice_semantic(
            item,
            mode,
            index,
            choice_label,
        )
        result.append(
            {
                "label": choice_key,
                "code": choice_code,
                "text": choice_label,
                "choice_key": choice_key,
                "choice_code": choice_code,
                "choice_label": choice_label,
                "semantic_value": semantic_value,
                "semantic_state": semantic_state,
            }
        )
    return result


def startup_status_to_dict(status: StartupStatus) -> Dict[str, Any]:
    return {
        "startup_ambiguity_percent": status.startup_ambiguity_percent,
        "interview_progress_percent": status.progress_percent,
        "interview_remaining_percent": status.remaining_percent,
        "required_resolved": status.required_resolved,
        "required_total": status.required_total,
        "startup_ready": status.startup_ready,
        "minimum_frame_resolved": status.minimum_frame_resolved,
        "minimum_frame_total": status.minimum_frame_total,
        "minimum_frame_ready": status.minimum_frame_ready,
        "full_interview_complete": status.full_interview_complete,
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
                "answer_role": _answer_role_for_item(item),
                "required_for_minimum_frame": _requires_minimum_frame(item),
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
            "answer_role": _answer_role_for_item(round_.next_question),
            "required_for_minimum_frame": _requires_minimum_frame(
                round_.next_question
            ),
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
        "minimum_frame_ready: "
        f"{'yes' if status.minimum_frame_ready else 'no'} "
        f"({status.minimum_frame_resolved}/{status.minimum_frame_total})",
        "full_interview_complete: "
        f"{'yes' if status.full_interview_complete else 'no'}",
        f"active_mode: {status.active_mode}",
        f"discretion_level: {status.discretion_level} ({status.discretion_label})",
        f"profile_path: {status.profile_path}",
    ]


def format_startup_summary(summary: Dict[str, Any]) -> List[str]:
    lines = [
        f"startup_summary: {summary['schema']}",
        f"world_id: {summary['world_id']}",
        f"question_pack_id: {summary.get('question_pack_id')}",
        f"defaults_revision: {summary.get('defaults_revision')}",
        f"startup_ready: {'yes' if summary['startup_ready'] else 'no'}",
        "minimum_frame_ready: "
        f"{'yes' if summary['minimum_frame_ready'] else 'no'}",
        "full_interview_complete: "
        f"{'yes' if summary['full_interview_complete'] else 'no'}",
        f"interview_progress: {summary['interview_progress_percent']}%",
        f"side_effect_status: {summary['side_effect_status']}",
    ]
    for section in (
        "project_intent",
        "workflow_preferences",
        "explicit_world_assertions",
        "unresolved_blockers",
        "optional_unknowns",
    ):
        lines.append(f"{section}:")
        records = summary[section]
        if not records:
            lines.append("\tnone")
            continue
        lines.extend(
            "\t".join(
                [
                    str(item["question_id"]),
                    str(item["dimension"]),
                    str(item.get("semantic_value") or item.get("state") or "unknown"),
                ]
            )
            for item in records
        )
    lines.append("answers:")
    if summary["answers"]:
        lines.extend(
            "\t".join(
                [
                    str(item["question_id"]),
                    str(item["dimension"]),
                    str(item["status"]),
                    str(item["answer"]),
                ]
            )
            for item in summary["answers"]
        )
    else:
        lines.append("\tnone")
    lines.append("unresolved:")
    if summary["unresolved"]:
        lines.extend(
            f"\t{item['question_id']}\t{item['dimension']}"
            for item in summary["unresolved"]
        )
    else:
        lines.append("\tnone")
    lines.append("next_actions:")
    lines.extend(f"\t{item}" for item in summary["next_actions"])
    return lines


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
            lines.append(
                "agent_fill: external runtime may suggest candidates after the user frame, "
                "subject to local policy"
            )
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
