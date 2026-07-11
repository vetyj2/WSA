from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..repositories import TicketRecord, WorldRepository
from ..tickets import CANDIDATE_TICKET_TYPES


class TicketSelectionError(ValueError):
    """Raised when a guided action cannot identify one safe ticket."""


@dataclass(frozen=True)
class GuidedTicketSelection:
    ticket: TicketRecord
    action: str
    eligible_count: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema": "wsa.ticket.guided_selection.v1",
            "ticket_id": self.ticket.ticket_id,
            "ticket_type": self.ticket.ticket_type,
            "title": self.ticket.title,
            "status": self.ticket.status,
            "risk": self.ticket.risk,
            "action": self.action,
            "eligible_count": self.eligible_count,
            "selection_policy": "single_eligible_ticket_only",
            "side_effect_status": "read_only_selection_no_state_transition",
        }


def select_guided_ticket(
    repo: WorldRepository,
    action: str,
) -> GuidedTicketSelection:
    """Resolve one concrete ticket without guessing across equivalent choices."""

    normalized = action.strip().lower()
    if normalized not in {"inspect", "review", "apply"}:
        raise ValueError(f"unsupported guided ticket action: {action}")

    concrete = [
        ticket
        for ticket in repo.list_tickets()
        if ticket.ticket_type not in CANDIDATE_TICKET_TYPES
        and repo.list_ticket_changes(ticket.ticket_id)
    ]
    if normalized == "inspect":
        approved = [ticket for ticket in concrete if ticket.status == "approved"]
        candidates = approved or [
            ticket for ticket in concrete if ticket.status == "proposed"
        ]
        resolved_action = "apply" if approved else "review"
    else:
        required_status = "proposed" if normalized == "review" else "approved"
        candidates = [
            ticket for ticket in concrete if ticket.status == required_status
        ]
        resolved_action = normalized

    if not candidates:
        required = "proposed" if resolved_action == "review" else "approved"
        raise TicketSelectionError(
            f"no concrete {required} ticket is available for {resolved_action}"
        )
    if len(candidates) > 1:
        choices = "; ".join(
            f"{ticket.title} [{ticket.status}] ({ticket.ticket_id})"
            for ticket in candidates
        )
        raise TicketSelectionError(
            f"multiple tickets are eligible for {resolved_action}; inspect and choose one: "
            f"{choices}"
        )
    return GuidedTicketSelection(candidates[0], resolved_action, len(candidates))


def list_guided_candidates(
    repo: WorldRepository,
    action: str,
) -> List[TicketRecord]:
    """Return concrete candidates for diagnostics without selecting one."""

    normalized = action.strip().lower()
    required_status = {
        "review": "proposed",
        "apply": "approved",
    }.get(normalized)
    if required_status is None:
        raise ValueError(f"unsupported guided ticket action: {action}")
    return [
        ticket
        for ticket in repo.list_tickets(status=required_status)
        if ticket.ticket_type not in CANDIDATE_TICKET_TYPES
        and repo.list_ticket_changes(ticket.ticket_id)
    ]
