from __future__ import annotations

import argparse
from pathlib import Path

from .cli_tickets import (
    run_ticket_apply,
    run_ticket_apply_next,
    run_ticket_compose,
    run_ticket_list,
    run_ticket_materialize,
    run_ticket_merge,
    run_ticket_next,
    run_ticket_review,
    run_ticket_review_next,
    run_ticket_show,
    run_ticket_split,
)


def dispatch_ticket_command(
    args: argparse.Namespace,
    workspace: Path,
    language: str,
    parser: argparse.ArgumentParser,
) -> int:
    if args.ticket_command == "list":
        return run_ticket_list(workspace, args.world_id, args.status)
    if args.ticket_command == "show":
        return run_ticket_show(
            workspace,
            args.world_selector,
            args.ticket_id,
            args.format,
            language=language,
        )
    if args.ticket_command == "next":
        return run_ticket_next(
            workspace,
            args.world_selector,
            args.format,
            language=language,
        )
    if args.ticket_command == "review-next":
        return run_ticket_review_next(
            workspace,
            args.world_selector,
            args.format,
        )
    if args.ticket_command == "apply-next":
        return run_ticket_apply_next(
            workspace,
            args.world_selector,
            args.format,
        )
    if args.ticket_command in {"compose", "amend"}:
        return run_ticket_compose(
            workspace,
            args.world_selector,
            title=args.title,
            add_entity=args.add_entity,
            add_fact=args.add_fact,
            add_edge=args.add_edge,
            add_timeline=args.add_timeline,
            accept_candidate=getattr(args, "accept_candidate", None),
            revise_ticket=(
                args.ticket_id if args.ticket_command == "amend" else None
            ),
            skip_index=getattr(args, "skip_index", []),
            risk=args.risk,
            compact=args.compact,
            write_ticket=args.write_ticket,
            output_format=args.format,
            language=language,
        )
    if args.ticket_command == "split":
        return run_ticket_split(
            workspace,
            args.world_selector,
            args.ticket_id,
            args.part,
            titles=args.part_title,
            write_ticket=args.write_ticket,
            output_format=args.format,
        )
    if args.ticket_command == "merge":
        return run_ticket_merge(
            workspace,
            args.world_selector,
            args.ticket_ids,
            title=args.title,
            risk=args.risk,
            compact=args.compact,
            write_ticket=args.write_ticket,
            output_format=args.format,
        )
    if args.ticket_command in {"apply", "approve"}:
        return run_ticket_apply(
            workspace,
            args.world_id,
            args.ticket_id,
            allow_proposed_compat=args.ticket_command == "approve",
        )
    if args.ticket_command == "review":
        return run_ticket_review(
            workspace,
            args.world_id,
            args.ticket_id,
            args.format,
        )
    if args.ticket_command == "materialize":
        return run_ticket_materialize(
            workspace,
            args.world_id,
            args.candidate_ticket_id,
            args.changes_json,
            args.write_ticket,
            args.format,
        )
    parser.parse_args(["ticket", "--help"])
    raise AssertionError("ticket help should exit")
