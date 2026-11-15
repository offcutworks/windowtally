"""Reads Claude Code transcripts (``~/.claude/projects/**/*.jsonl``) into the ledger, incrementally.

What a transcript carries, as Claude Code 2.1 writes it (one JSON object per line):
    assistant       one line per content block of a response; every line of one response repeats its
                    ``message.id`` and ``requestId`` with the usage known so far, so the last line carries the
                    final usage. Also on the line: timestamp, sessionId, agentId (a subagent's line), entrypoint
                    (claude-desktop, cli, sdk-cli), version, cwd, requestedModel, effort, and ``message.model``.
                    A ``<synthetic>`` model marks a locally generated message with no API usage. A turn a plan limit
                    refused is such a message flagged ``isApiErrorMessage`` with ``error`` ``rate_limit`` (HTTP 429),
                    its text "You've hit your session limit" or "weekly limit"; from Claude Code 2.1.299 it also
                    carries ``quotaLimits`` (and ``apiErrorParams.rate_limit_info``) naming the window,
                    ``rateLimitType`` ``five_hour`` or ``seven_day``, and its reset, ``resetsAt`` in epoch seconds.
    user            a prompt or a tool result; ``promptId`` groups the lines of one prompt, and a prompt's line names
                    ``permissionMode``, the permission mode its turn runs in. The result of a command
                    started in the background carries ``toolUseResult.backgroundTaskId``, that of a subagent started
                    so ``toolUseResult.status`` ``async_launched`` beside its ``agentId``, and that of a task the
                    session stopped itself ``toolUseResult.task_id`` under a ``message`` that opens "Successfully
                    stopped task". A task's end reaches its session as a line of ``origin.kind``
                    ``task-notification`` whose text opens with the task, ``<task-id>``, and names how it ended,
                    ``<status>``, before its ``<summary>``, which is free text.
    queue-operation ``operation`` ``enqueue`` with that notification as its ``content``, written as the task ends,
                    whether its session is at work or idle. A notification with no ``<status>`` is an event of a
                    task that watches (a monitor), not an end.
    bridge-session  written by a desktop session: ``ownerAccountUuid`` names the account the session belongs to.
    custom-title    ``customTitle``: the title the desktop app shows for the session, written again as it changes.
    ai-title        ``aiTitle``: the title Claude Code makes up itself, which a ``custom-title`` stands before.
    permission-mode ``permissionMode``: the session's permission mode, written as it changes, with no time.
A subagent's transcript lives at ``<session>/subagents/agent-<id>.jsonl`` and carries its parent's sessionId; it holds
no title line, and its limit stops are its parent's turn's, so only a main session's stop is recorded. Title lines
carry no time, so of two a transcript holds the later one stands. (Measured on the development machine, 2026-11-08,
Claude Code 2.1.308 and 2.1.310: every card the desktop app keeps but one shows the title of its transcript's last
``custom-title`` line, and every ``rate_limit`` line read then said a session or weekly limit was hit.)

A session's permission mode is the one its main transcript names last, on a prompt's line or a ``permission-mode``
line, since a ``permission-mode`` line carries no time; a subagent's transcript is not read for it. The desktop app,
adopting a session of another account, takes the mode from its transcript's last lines where they name one and its
effort from nothing, so the window says what the session ran with for the user to set again (``sessions``). (Measured
on the development machine, 2026-11-11, over the main transcripts of Claude Code 2.1.269 to 2.1.321: the modes named
were ``auto``, ``acceptEdits``, ``default``, ``bypassPermissions`` and ``plan``.)

Each file is read from its cursor to its last complete line; a line still being written is left for the next
pass. A file that shrank below its cursor was rewritten and is read again from the start — the upserts below
make a second read harmless.

The kinds of line read grew after transcripts had been read (``KINDS``), and the ledger records which kinds every
transcript has been read for. A ledger read for fewer has the part already read of each main transcript read once
more, for titles, limit stops and permission modes alone, before any new line (``_catch_up``): reading everything again
would upsert every response again, the whole work of a first import. A title the catch-up reads takes the place only of
one Claude Code made up, and only as the app's, and a mode it reads only stands where the session has none, so a
catch-up that stopped part way and runs again never puts an older title or mode back over a newer one the reader found
since. The ledger records the kinds once every file was read; a file that could not be read leaves the catch-up to run
again at the next pass.

A background task is read for one question: which sessions started work that never reported back (``sessions``). Its
start is its main session's line; its end is matched by the task's id alone, whatever transcript holds it, since the
end of a task whose session's process had gone was written into the transcript that session went on in. (Measured on
the development machine, 2026-11-10, Claude Code 2.1.280 to 2.1.310: all but a few of the commands started in the
background had a notification queued or were stopped by their session, and all but a few subagents had one; every
notification read opened with its task's id and named its status before its summary.)
A task started again under its id keeps its latest start and its latest end, and is unfinished while the end stands
before the start. A task that only watches is not work and is not read. Background tasks are not caught up: only
those of the last day are ever asked for, so the lines read from here on hold them.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .ledger import Cursor, Ledger
from .pricing import price_for, response_cost
from .timeutil import parse_iso

log = logging.getLogger(__name__)

_ASSISTANT = b'"type":"assistant"'
_BRIDGE = b'"type":"bridge-session"'
_USER = b'"type":"user"'
_PROMPT = b'"promptId"'
_CUSTOM_TITLE = b'"type":"custom-title"'
_AI_TITLE = b'"type":"ai-title"'
_MODE = b'"permissionMode"'
_API_ERROR = b'"isApiErrorMessage":true'
_QUEUE = b'"type":"queue-operation"'
# What a line that starts or ends a background task holds: two marks of a start, two of an end.
_TASK_MARKS = (b'"backgroundTaskId"', b'"async_launched"', b"<task-notification>", b'"task_type"')
# A notification's own fields stand before its summary; what follows is free text that may quote another's.
_NOTIFICATION = re.compile(r"<task-notification>\s*<task-id>([^<]+)</task-id>(.*?)(?:<summary>|\Z)", re.DOTALL)
_STOPPED = "Successfully stopped task"

# The kinds of line the reader takes, kept in the ledger's meta table under KINDS_KEY: "1" responses, owners and
# prompts; "2" titles and limit stops besides; "3" permission modes besides. Background tasks are read without a kind of
# their own (see above).
KINDS = "3"
KINDS_KEY = "transcript_kinds"

LIMIT_WINDOWS = ("five_hour", "seven_day")
TITLE_SOURCES = {"custom-title": ("customTitle", "custom"), "ai-title": ("aiTitle", "ai")}

# A title the app shows stands before Claude Code's own; within one source the one read last stands.
_UPSERT_TITLE = """
INSERT INTO session_titles (session_id, title, source) VALUES (?, ?, ?)
ON CONFLICT(session_id) DO UPDATE SET title = excluded.title, source = excluded.source
WHERE excluded.source = 'custom' OR session_titles.source = 'ai'
"""
# The catch-up's: a title it reads takes the place only of Claude Code's own, and only as the app's.
_CATCH_UP_TITLE = """
INSERT INTO session_titles (session_id, title, source) VALUES (?, ?, ?)
ON CONFLICT(session_id) DO UPDATE SET title = excluded.title, source = excluded.source
WHERE excluded.source = 'custom' AND session_titles.source = 'ai'
"""
# The mode read last stands; the catch-up's stands only where the reader found none, having read older lines.
_UPSERT_MODE = """
INSERT INTO session_modes (session_id, mode) VALUES (?, ?)
ON CONFLICT(session_id) DO UPDATE SET mode = excluded.mode
"""
_CATCH_UP_MODE = "INSERT OR IGNORE INTO session_modes (session_id, mode) VALUES (?, ?)"
_INSERT_STOP = """
INSERT OR IGNORE INTO limit_stops (line_uuid, session_id, t, kind, resets_at, entrypoint)
VALUES (:line_uuid, :session_id, :t, :kind, :resets_at, :entrypoint)
"""

# A start and an end may be read in either order, and from different transcripts: each writes its own columns. A task
# started again under its id (a subagent gone on with) keeps its latest start and its latest end, so it is unfinished
# while the end stands before the start.
_START_TASK = """
INSERT INTO background_tasks (task_id, session_id, kind, started) VALUES (?, ?, ?, ?)
ON CONFLICT(task_id) DO UPDATE SET session_id = excluded.session_id, kind = excluded.kind,
    started = MAX(COALESCE(background_tasks.started, excluded.started), excluded.started)
"""
_END_TASK = """
INSERT INTO background_tasks (task_id, ended) VALUES (?, ?)
ON CONFLICT(task_id) DO UPDATE SET ended = MAX(COALESCE(background_tasks.ended, excluded.ended), excluded.ended)
"""

_UPSERT_RESPONSE = """
INSERT INTO responses (message_id, request_id, t, session_id, agent_id, entrypoint, version, cwd, model,
    requested_model, effort, speed, input_tokens, output_tokens, thinking_tokens, cache_read_tokens,
    cache_write_5m_tokens, cache_write_1h_tokens, web_search_requests, web_fetch_requests, cost_usd)
VALUES (:message_id, :request_id, :t, :session_id, :agent_id, :entrypoint, :version, :cwd, :model,
    :requested_model, :effort, :speed, :input_tokens, :output_tokens, :thinking_tokens, :cache_read_tokens,
    :cache_write_5m_tokens, :cache_write_1h_tokens, :web_search_requests, :web_fetch_requests, :cost_usd)
ON CONFLICT(message_id) DO UPDATE SET
    t = MIN(responses.t, excluded.t),
    speed = excluded.speed,
    input_tokens = excluded.input_tokens,
    output_tokens = excluded.output_tokens,
    thinking_tokens = excluded.thinking_tokens,
    cache_read_tokens = excluded.cache_read_tokens,
    cache_write_5m_tokens = excluded.cache_write_5m_tokens,
    cache_write_1h_tokens = excluded.cache_write_1h_tokens,
    web_search_requests = excluded.web_search_requests,
    web_fetch_requests = excluded.web_fetch_requests,
    cost_usd = excluded.cost_usd
WHERE excluded.output_tokens >= responses.output_tokens
"""


@dataclass
class TranscriptStats:
    files_seen: int = 0
    files_read: int = 0
    bytes_read: int = 0
    responses: int = 0
    unparseable_lines: int = 0
    titles: int = 0
    modes: int = 0          # lines read that name a main session's permission mode; the catch-up counts sessions
    limit_stops: int = 0
    tasks_started: int = 0  # lines read that start a background task
    tasks_ended: int = 0    # lines read that end one; a task's end is often written twice, queued and delivered
    caught_up: int = 0      # files whose part already read was read again for the kinds of line added


def _transcript_files(root: Path) -> Iterator[os.DirEntry]:
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.name.endswith(".jsonl") and entry.is_file(follow_symlinks=False):
                        yield entry
        except OSError as exc:
            log.warning("Cannot list %s: %s", current, exc)


def _is_main(entry: os.DirEntry) -> bool:
    """Whether a transcript is a main session's rather than a subagent's (``<session>/subagents/agent-<id>.jsonl``)."""
    return Path(entry.path).parent.name != "subagents"


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def response_row(entry: dict) -> dict | None:
    """The ledger row for one assistant line, or None when the line carries no API usage."""
    message = entry.get("message") or {}
    usage = message.get("usage")
    model = message.get("model")
    message_id = message.get("id")
    t = parse_iso(entry.get("timestamp"))
    session_id = entry.get("sessionId")
    if not usage or not message_id or not model or model == "<synthetic>" or t is None or not session_id:
        return None
    creation = usage.get("cache_creation") or {}
    write_5m = creation.get("ephemeral_5m_input_tokens")
    write_1h = creation.get("ephemeral_1h_input_tokens")
    if write_5m is None and write_1h is None:
        # No TTL breakdown: the API's default TTL is five minutes.
        write_5m, write_1h = usage.get("cache_creation_input_tokens"), 0
    server_tools = usage.get("server_tool_use") or {}
    row = {
        "message_id": message_id,
        "request_id": entry.get("requestId"),
        "t": t,
        "session_id": session_id,
        "agent_id": entry.get("agentId"),
        "entrypoint": entry.get("entrypoint"),
        "version": entry.get("version"),
        "cwd": entry.get("cwd"),
        "model": model,
        "requested_model": entry.get("requestedModel"),
        "effort": entry.get("effort"),
        "speed": usage.get("speed"),
        "input_tokens": _int(usage.get("input_tokens")),
        "output_tokens": _int(usage.get("output_tokens")),
        "thinking_tokens": _int((usage.get("output_tokens_details") or {}).get("thinking_tokens")),
        "cache_read_tokens": _int(usage.get("cache_read_input_tokens")),
        "cache_write_5m_tokens": _int(write_5m),
        "cache_write_1h_tokens": _int(write_1h),
        "web_search_requests": _int(server_tools.get("web_search_requests")),
        "web_fetch_requests": _int(server_tools.get("web_fetch_requests")),
    }
    row["cost_usd"] = response_cost(
        model, input_tokens=row["input_tokens"], output_tokens=row["output_tokens"],
        cache_read_tokens=row["cache_read_tokens"], cache_write_5m_tokens=row["cache_write_5m_tokens"],
        cache_write_1h_tokens=row["cache_write_1h_tokens"], speed=row["speed"])
    return row


@dataclass(frozen=True)
class Repricing:
    """What ``reprice`` did: how many responses it priced, and the models whose responses still have no list price,
    each with how many it has."""

    priced: int
    unpriced: tuple[tuple[str, int], ...]


def reprice(ledger: Ledger) -> Repricing:
    """Prices every response stored without a cost whose model the price table now names, from the tokens the ledger
    kept; a response is priced once, when its line is read, so a model added to the table after its responses were read
    leaves them unpriced until this runs. Only the responses of a model the table now names are read; the models still
    unpriced are counted and returned for the pass to name."""
    counts = ledger.db.execute(
        "SELECT model, COUNT(*) FROM responses WHERE cost_usd IS NULL GROUP BY model").fetchall()
    left = tuple(sorted((model or "no model", count) for model, count in counts if price_for(model) is None))
    priced: list[tuple[float, str]] = []
    for model in (model for model, _ in counts if price_for(model) is not None):
        rows = ledger.db.execute(
            "SELECT message_id, input_tokens, output_tokens, cache_read_tokens, cache_write_5m_tokens, "
            "cache_write_1h_tokens, speed FROM responses WHERE cost_usd IS NULL AND model=?", (model,))
        for message_id, input_tokens, output_tokens, cache_read, write_5m, write_1h, speed in rows:
            priced.append((response_cost(model, input_tokens=input_tokens, output_tokens=output_tokens,
                                         cache_read_tokens=cache_read, cache_write_5m_tokens=write_5m,
                                         cache_write_1h_tokens=write_1h, speed=speed), message_id))
    if priced:
        with ledger.transaction():
            ledger.db.executemany("UPDATE responses SET cost_usd=? WHERE message_id=? AND cost_usd IS NULL", priced)
    return Repricing(len(priced), left)


def stop_row(entry: dict) -> dict | None:
    """The ledger row of a main session's turn a plan limit refused, or None for any other line. The window and its
    reset are read where the line carries them, and left unknown where it does not, as before Claude Code 2.1.299."""
    if entry.get("isApiErrorMessage") is not True or entry.get("error") != "rate_limit":
        return None
    if entry.get("isSidechain") or entry.get("agentId"):
        return None
    line_uuid, session_id, t = entry.get("uuid"), entry.get("sessionId"), parse_iso(entry.get("timestamp"))
    if not line_uuid or not session_id or t is None:
        return None
    quota = entry.get("quotaLimits")
    if not isinstance(quota, dict):
        params = entry.get("apiErrorParams")
        quota = params.get("rate_limit_info") if isinstance(params, dict) else None
    quota = quota if isinstance(quota, dict) else {}
    kind, resets = quota.get("rateLimitType"), quota.get("resetsAt")
    return {"line_uuid": line_uuid, "session_id": session_id, "t": t,
            "kind": kind if kind in LIMIT_WINDOWS else None,
            "resets_at": float(resets) if isinstance(resets, (int, float)) and not isinstance(resets, bool) else None,
            "entrypoint": entry.get("entrypoint")}


def title_row(entry: dict) -> tuple[str, str, str] | None:
    """``(session_id, title, source)`` of a title line, or None for any other line or a title with no words."""
    found = TITLE_SOURCES.get(entry.get("type"))
    if found is None:
        return None
    key, source = found
    session_id, title = entry.get("sessionId"), entry.get(key)
    if not session_id or not isinstance(title, str) or not title.strip():
        return None
    return session_id, title, source


def mode_row(entry: dict) -> tuple[str, str] | None:
    """``(session_id, mode)`` of a line naming its session's permission mode — a main session's prompt or a
    ``permission-mode`` line — or None for any other line."""
    if entry.get("type") not in ("user", "permission-mode") or entry.get("isSidechain"):
        return None
    session_id, mode = entry.get("sessionId"), entry.get("permissionMode")
    if not session_id or not isinstance(mode, str) or not mode:
        return None
    return session_id, mode


def task_start(entry: dict) -> tuple[str, str, str, float] | None:
    """``(task_id, session_id, kind, started)`` of the line on which a main session starts a background task, a
    ``command`` or an ``agent``, or None for any other line. A subagent's own background task is its parent's
    turn's, as its limit stop is, and is not recorded."""
    result = entry.get("toolUseResult")
    if entry.get("type") != "user" or entry.get("isSidechain") or not isinstance(result, dict):
        return None
    session_id, t = entry.get("sessionId"), parse_iso(entry.get("timestamp"))
    if not session_id or t is None:
        return None
    command, agent = result.get("backgroundTaskId"), result.get("agentId")
    if isinstance(command, str) and command:
        return command, session_id, "command", t
    if result.get("status") == "async_launched" and isinstance(agent, str) and agent:
        return agent, session_id, "agent", t
    return None


def task_end(entry: dict) -> tuple[str, float] | None:
    """``(task_id, ended)`` of the background task the line says has ended, or None for any other line: a
    notification, queued or delivered, that opens with the task's id and names how it ended before its summary, or
    the result of a stop the session made itself, known by its message. Read otherwise, a line would end a task its
    free text only quotes, or one a tool merely asked about."""
    t = parse_iso(entry.get("timestamp"))
    if t is None:
        return None
    text = None
    if entry.get("type") == "queue-operation":
        text = entry.get("content") if entry.get("operation") == "enqueue" else None
    elif entry.get("type") == "user":
        result, origin = entry.get("toolUseResult"), entry.get("origin")
        if isinstance(result, dict) and isinstance(result.get("task_id"), str):
            message = result.get("message")
            stopped = isinstance(message, str) and message.startswith(_STOPPED) and result["task_id"]
            return (result["task_id"], t) if stopped else None
        if isinstance(origin, dict) and origin.get("kind") == "task-notification":
            message = entry.get("message")
            text = message.get("content") if isinstance(message, dict) else None
    found = _NOTIFICATION.match(text) if isinstance(text, str) else None
    if found is None or "<status>" not in found.group(2):
        return None
    return found.group(1), t


def _is_title(line: bytes) -> bool:
    return _CUSTOM_TITLE in line or _AI_TITLE in line


def _is_task(line: bytes) -> bool:
    return (_USER in line or _QUEUE in line) and any(mark in line for mark in _TASK_MARKS)


def _ingest_tasks(ledger: Ledger, entry: dict, stats: TranscriptStats) -> None:
    started = task_start(entry)
    if started is not None:
        ledger.db.execute(_START_TASK, started)
        stats.tasks_started += 1
    ended = task_end(entry)
    if ended is not None:
        ledger.db.execute(_END_TASK, ended)
        stats.tasks_ended += 1


def _ingest_line(ledger: Ledger, line: bytes, stats: TranscriptStats, main: bool = True) -> None:
    """Reads one complete line; ``main`` is whether it comes from a main session's transcript, the only one read for
    the session's permission mode."""
    is_assistant = _ASSISTANT in line
    is_bridge = not is_assistant and _BRIDGE in line
    is_prompt = not is_assistant and not is_bridge and _USER in line and _PROMPT in line
    is_title = not (is_assistant or is_bridge or is_prompt) and _is_title(line)
    is_mode = main and not (is_assistant or is_bridge) and _MODE in line
    is_task = not is_assistant and _is_task(line)
    if not (is_assistant or is_bridge or is_prompt or is_title or is_mode or is_task):
        return
    try:
        entry = json.loads(line)
    except ValueError:
        stats.unparseable_lines += 1
        return
    kind = entry.get("type")
    if kind == "assistant":
        row = response_row(entry)
        if row is not None:
            ledger.db.execute(_UPSERT_RESPONSE, row)
            stats.responses += 1
        else:
            stop = stop_row(entry)
            if stop is not None:
                ledger.db.execute(_INSERT_STOP, stop)
                stats.limit_stops += 1
    elif kind in TITLE_SOURCES:
        titled = title_row(entry)
        if titled is not None:
            ledger.db.execute(_UPSERT_TITLE, titled)
            stats.titles += 1
    elif kind == "bridge-session":
        session_id, owner = entry.get("sessionId"), entry.get("ownerAccountUuid")
        if session_id and owner:
            ledger.db.execute("INSERT OR IGNORE INTO session_owners(session_id, account_uuid) VALUES (?, ?)",
                              (session_id, owner.lower()))
    elif kind == "user" and not entry.get("isSidechain"):
        prompt_id, session_id, t = entry.get("promptId"), entry.get("sessionId"), parse_iso(entry.get("timestamp"))
        if prompt_id and session_id and t is not None:
            ledger.db.execute("INSERT OR IGNORE INTO prompts(prompt_id, session_id, t) VALUES (?, ?, ?)",
                              (prompt_id, session_id, t))
    if is_mode:
        moded = mode_row(entry)
        if moded is not None:
            ledger.db.execute(_UPSERT_MODE, moded)
            stats.modes += 1
    # A line taken for an assistant's by words it only quotes is read by its kind, as the branches above read it.
    if is_task or (is_assistant and kind != "assistant"):
        _ingest_tasks(ledger, entry, stats)


def _ingest_file(ledger: Ledger, entry: os.DirEntry, stats: TranscriptStats) -> None:
    status = entry.stat()
    previous = ledger.cursor(entry.path)
    if previous and previous.size == status.st_size and previous.mtime == status.st_mtime:
        return
    offset = previous.offset if previous and status.st_size >= previous.offset else 0
    main = _is_main(entry)
    with open(entry.path, "rb") as handle, ledger.transaction():
        handle.seek(offset)
        for line in handle:
            if not line.endswith(b"\n"):
                break
            offset += len(line)
            stats.bytes_read += len(line)
            _ingest_line(ledger, line, stats, main)
        ledger.set_cursor(entry.path, Cursor(offset=offset, size=status.st_size, mtime=status.st_mtime))
    stats.files_read += 1


def _catch_up_file(ledger: Ledger, entry: os.DirEntry, stats: TranscriptStats) -> None:
    """Reads the part of one main transcript already read for titles, limit stops and permission modes alone. A file
    that shrank below its cursor is read again whole by the reader itself, and a file never read has no part to catch
    up."""
    previous = ledger.cursor(entry.path)
    if previous is None or previous.offset == 0 or entry.stat().st_size < previous.offset:
        return
    titles: dict[tuple[str, str], str] = {}   # (session, source) -> the title read last
    modes: dict[str, str] = {}                # session -> the mode read last
    stops = []
    with open(entry.path, "rb") as handle:
        read = 0
        for line in handle:
            read += len(line)
            if read > previous.offset:
                break
            if _is_title(line) or (_ASSISTANT in line and _API_ERROR in line) or _MODE in line:
                try:
                    found = json.loads(line)
                except ValueError:
                    continue
                titled = title_row(found)
                if titled is not None:
                    titles[(titled[0], titled[2])] = titled[1]
                    continue
                moded = mode_row(found)
                if moded is not None:
                    modes[moded[0]] = moded[1]
                    continue
                stop = stop_row(found)
                if stop is not None:
                    stops.append(stop)
    with ledger.transaction():
        for (session_id, source), title in sorted(titles.items(), key=lambda item: item[0][1] == "custom"):
            ledger.db.execute(_CATCH_UP_TITLE, (session_id, title, source))
        for session_id, mode in modes.items():
            ledger.db.execute(_CATCH_UP_MODE, (session_id, mode))
        for stop in stops:
            ledger.db.execute(_INSERT_STOP, stop)
    stats.titles += len(titles)
    stats.modes += len(modes)
    stats.limit_stops += len(stops)
    stats.caught_up += 1


def _catch_up(ledger: Ledger, projects_dir: Path, stats: TranscriptStats) -> None:
    """Reads every main transcript's part already read for the kinds of line added since it was read, then records
    that every transcript is read for them; a file that cannot be read now leaves the record for a later pass."""
    unread = 0
    for entry in _transcript_files(projects_dir):
        if not _is_main(entry):
            continue
        try:
            _catch_up_file(ledger, entry, stats)
        except FileNotFoundError:
            continue
        except OSError as exc:
            unread += 1
            log.warning("Cannot read transcript %s again for its titles, limit stops and permission modes: %s",
                        entry.path, exc)
    if unread:
        log.warning("%d transcripts are to be read again for their titles, limit stops and permission modes at the "
                    "next pass", unread)
        return
    with ledger.transaction():
        ledger.set_meta(KINDS_KEY, KINDS)


def ingest_transcripts(ledger: Ledger, projects_dir: Path) -> TranscriptStats:
    """Reads every transcript's new complete lines, after the part already read of each where the ledger was read for
    fewer kinds of line than this code reads. A file that cannot be read is logged and retried next pass."""
    stats = TranscriptStats()
    if not projects_dir.is_dir():
        log.info("No transcript folder at %s", projects_dir)
        return stats
    if ledger.get_meta(KINDS_KEY) != KINDS:
        _catch_up(ledger, projects_dir, stats)
    for entry in _transcript_files(projects_dir):
        stats.files_seen += 1
        try:
            _ingest_file(ledger, entry, stats)
        except OSError as exc:
            log.warning("Cannot read transcript %s: %s", entry.path, exc)
    if stats.unparseable_lines:
        log.warning("%d transcript lines could not be parsed", stats.unparseable_lines)
    return stats
