from __future__ import annotations

from typing import Any, Dict, List


PARTICIPANT_SELECTION_PRIORITIES = (
    "verification_need",
    "targeted_objection",
    "owner",
    "unanswered_question",
)
MAX_PARTICIPANT_SELECTION_ITEMS = 16
PARTICIPANT_REFERENCE_KEYS = {
    "participant_id",
    "participant_ids",
    "actor_id",
    "actor_ids",
    "target_participant_id",
    "target_participant_ids",
    "target_actor_id",
    "target_actor_ids",
    "owner",
    "owners",
    "owner_id",
    "owner_ids",
    "owner_participant_id",
    "owner_participant_ids",
    "question_owner",
    "question_owner_id",
}


def choose_participant_contexts(
    context_packets: List[Dict[str, Any]],
    actor_states: Dict[str, Dict[str, Any]] | None = None,
    floor_state: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Choose a bounded participant subset while preserving the legacy fallback."""
    contexts = list(context_packets)
    participant_ids = [
        str(packet.get("participant_id"))
        for packet in contexts
        if packet.get("participant_id")
    ]
    if not participant_ids:
        return contexts
    signals = participant_selection_signals(
        participant_ids,
        actor_states or {},
        floor_state or {},
    )
    for priority in PARTICIPANT_SELECTION_PRIORITIES:
        targeted = signals[priority]
        selected_ids = [
            participant_id
            for participant_id in participant_ids
            if participant_id in targeted
        ]
        if not selected_ids:
            continue
        if len(selected_ids) == len(participant_ids):
            return contexts
        by_participant_id = {
            str(packet.get("participant_id")): packet
            for packet in contexts
            if packet.get("participant_id")
        }
        return [by_participant_id[participant_id] for participant_id in selected_ids]
    return contexts


def participant_selection_signals(
    participant_ids: List[str],
    actor_states: Dict[str, Dict[str, Any]],
    floor_state: Dict[str, Any],
) -> Dict[str, List[str]]:
    known_ids = participant_ids
    signals: Dict[str, List[str]] = {
        priority: [] for priority in PARTICIPANT_SELECTION_PRIORITIES
    }

    def add(priority: str, values: List[str]) -> None:
        for participant_id in known_ids:
            if participant_id in values and participant_id not in signals[priority]:
                signals[priority].append(participant_id)

    add(
        "verification_need",
        _metadata_participant_ids(floor_state.get("verification_needs"), known_ids),
    )
    for item in _as_list(floor_state.get("verification_queue"))[
        :MAX_PARTICIPANT_SELECTION_ITEMS
    ]:
        if _is_explicit_verification_need(item):
            add("verification_need", _metadata_participant_ids(item, known_ids))

    for key in (
        "targeted_objection",
        "targeted_objections",
        "blocking_objection",
        "blocking_objections",
        "objections",
    ):
        add(
            "targeted_objection",
            _metadata_participant_ids(floor_state.get(key), known_ids),
        )
    for key in (
        "owner",
        "owners",
        "active_question_owner",
        "active_question_owners",
        "question_owner",
        "question_owners",
        "domain_owner",
        "domain_owners",
        "ownership",
        "owner_participant_id",
        "owner_participant_ids",
    ):
        add("owner", _metadata_participant_ids(floor_state.get(key), known_ids))
    for key in ("unanswered_question", "unanswered_questions", "question_queue"):
        add(
            "unanswered_question",
            _metadata_participant_ids(floor_state.get(key), known_ids),
        )

    for participant_id in known_ids:
        state = actor_states.get(participant_id, {})
        add(
            "verification_need",
            _metadata_participant_ids(state.get("verification_needs"), known_ids),
        )
        objections_received = _as_list(state.get("objections_received"))
        if objections_received:
            targeted = _metadata_participant_ids(objections_received, known_ids)
            add("targeted_objection", targeted or [participant_id])
        add(
            "targeted_objection",
            _metadata_participant_ids(state.get("objections_made"), known_ids),
        )
        if any(
            state.get(key) is True
            for key in ("owns_active_question", "owns_question", "is_owner")
        ):
            add("owner", [participant_id])
        for key in (
            "owner",
            "ownership",
            "owner_metadata",
            "domain_owner",
            "question_owner",
        ):
            add("owner", _metadata_participant_ids(state.get(key), known_ids))
        unanswered = _as_list(state.get("unanswered_questions"))
        if unanswered:
            targeted = _metadata_participant_ids(unanswered, known_ids)
            add("unanswered_question", targeted or [participant_id])
    return signals


def _metadata_participant_ids(
    value: Any,
    known_ids: List[str],
    depth: int = 0,
) -> List[str]:
    if depth > 2 or value in (None, "", []):
        return []
    if isinstance(value, str):
        return [value] if value in known_ids else []
    if isinstance(value, (tuple, list)):
        result: List[str] = []
        for item in list(value)[:MAX_PARTICIPANT_SELECTION_ITEMS]:
            for participant_id in _metadata_participant_ids(item, known_ids, depth + 1):
                if participant_id not in result:
                    result.append(participant_id)
        return result
    if not isinstance(value, dict):
        return []
    result = []
    for key, item in list(value.items())[:MAX_PARTICIPANT_SELECTION_ITEMS]:
        key_text = str(key)
        if key_text in known_ids and bool(item) and key_text not in result:
            result.append(key_text)
        if key_text in PARTICIPANT_REFERENCE_KEYS or depth < 2:
            for participant_id in _metadata_participant_ids(item, known_ids, depth + 1):
                if participant_id not in result:
                    result.append(participant_id)
    return result


def _is_explicit_verification_need(item: Any) -> bool:
    if not isinstance(item, dict):
        return True
    status = str(item.get("status") or "").strip().casefold()
    if any(token in status for token in ("resolved", "completed", "cleared", "dismissed")):
        return False
    if "recommended" in status and not any(
        item.get(key) is True for key in ("explicit", "required", "targeted")
    ):
        return False
    return True


def _as_list(value: Any) -> List[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [])]
    return [value]
