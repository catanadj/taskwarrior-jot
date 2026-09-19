"""CLI orchestration for timelog commands."""

from __future__ import annotations

import json
import sys
from typing import Any

from .models import CommandResult, DeletedTimelogItem, TimelogIngestResult, TimelogPendingResult, TimelogTrashResult
from .output import warn
from .timelog import (
    add_time_log,
    amend_time_log,
    cancel_time_session,
    delete_time_log,
    ingest_time_log,
    list_deleted_time_logs,
    list_time_sessions,
    report_time_logs,
    restore_deleted_time_log,
    start_time_session,
    stop_all_time_sessions,
    stop_time_session,
)


def run_timelog(ctx: Any, args: Any) -> CommandResult:
    command = args.timelog_command
    if command == "start":
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        payload = start_time_session(ctx.config, task, started_at=args.at)
        timewarrior = payload.get("timewarrior")
        if isinstance(timewarrior, dict) and timewarrior.get("error"):
            warn(f"Timewarrior: {timewarrior['error']}")
        return CommandResult("timelog-start", payload)
    if command == "stop":
        if args.all:
            if args.task_ref:
                raise RuntimeError("timelog stop --all does not accept a task reference")
            return CommandResult(
                "timelog-stop-all",
                stop_all_time_sessions(ctx.config, ctx.taskwarrior, stopped_at=args.at, scope=args.scope),
            )
        if not args.task_ref:
            raise RuntimeError("timelog stop requires a task reference or --all")
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        return CommandResult("timelog-stop", stop_time_session(ctx.config, task, stopped_at=args.at, scope=args.scope))
    if command == "pending":
        return CommandResult("timelog-pending", TimelogPendingResult(sessions=tuple(list_time_sessions(ctx.config))))
    if command == "cancel":
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        return CommandResult("timelog-cancel", cancel_time_session(ctx.config, task))
    if command == "add":
        task = ctx.taskwarrior.resolve_task(args.task_ref)
        return CommandResult(
            "timelog-add",
            add_time_log(ctx.config, task, started_at=args.started_at, stopped_at=args.stopped_at, scope=args.scope),
        )
    if command == "amend":
        return CommandResult("timelog-amend", amend_time_log(ctx.config, args.key, started_at=args.started_at, stopped_at=args.stopped_at))
    if command == "delete":
        if not args.yes:
            raise RuntimeError("timelog delete requires --yes")
        return CommandResult("timelog-delete", delete_time_log(ctx.config, args.key))
    if command == "trash":
        return CommandResult(
            "timelog-trash",
            TimelogTrashResult(items=tuple(DeletedTimelogItem.from_mapping(item) for item in list_deleted_time_logs(ctx.config))),
        )
    if command == "restore":
        return CommandResult("timelog-restore", restore_deleted_time_log(ctx.config, args.reference))
    if command == "report":
        if args.csv and args.json:
            raise RuntimeError("timelog report --csv cannot be combined with --json")
        return CommandResult(
            "timelog-report-csv" if args.csv else "timelog-report",
            report_time_logs(
                ctx.config,
                period=args.period,
                project=args.project,
                task_ref=args.task,
                chain_id=args.chain,
                details=bool(args.details or args.csv),
                since=args.since,
                until=args.until,
            ),
        )
    if command != "ingest":
        raise RuntimeError(f"unknown timelog command '{command}'")
    old_line = sys.stdin.readline()
    new_line = sys.stdin.readline()
    if not old_line or not new_line:
        raise RuntimeError("timelog ingest requires two JSON lines on stdin")
    try:
        old = json.loads(old_line)
        new = json.loads(new_line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid hook JSON: {exc}") from exc
    return CommandResult(
        "timelog-ingest",
        TimelogIngestResult.from_mapping(
            ingest_time_log(ctx.config, old, new, scope=args.scope, stopped_at=args.stopped_at)
        ),
    )
