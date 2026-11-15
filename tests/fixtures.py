"""A synthetic machine for the tests: Claude Code's folder, the desktop app's folder and WindowTally's folder, written
in the formats the real producers write (Claude Code 2.1 transcripts, the app's version-2 usage history, the
account sync's store and records, the plugin's version-1 readings) and the ones the user writes (WindowTally's bills
file and settings, a bill archive's manifest). Every account, address, bill and figure is synthetic. Beside it,
``scripts_on`` reads what a written page could run, ``page_headings`` a history page's headings, and ``laid_out`` the
History window's blocks with each switched section's every view in its place."""

from __future__ import annotations

import csv
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent.parent
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from windowtally.paths import MachinePaths  # noqa: E402  (the tool folder must be importable first)
from windowtally_gui.history_model import Switch  # noqa: E402

ACCOUNT_A = "aaaaaaaa-0000-4000-8000-000000000001"
ACCOUNT_B = "bbbbbbbb-0000-4000-8000-000000000002"
ORG_A = "0a0a0a0a-0000-4000-8000-00000000000a"
ORG_B = "0b0b0b0b-0000-4000-8000-00000000000b"
EMAIL_A = "alpha@example.com"
EMAIL_B = "beta@example.com"


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.found.append("<script" + "".join(f" {name}" for name, _value in attrs) + ">")
        for name, value in attrs:
            if name.startswith("on"):
                self.found.append(f"<{tag} {name}>")
            elif (value or "").strip().lower().startswith("javascript:"):
                self.found.append(f"<{tag} {name}=javascript:>")


def scripts_on(page: str) -> list[str]:
    """Everything in ``page`` a browser would run, in order, read by an HTML parser rather than by pattern, so text in
    an attribute's value is never taken for a script: each ``<script>`` element with its attributes' names, each
    handler attribute (``<tag onclick>``) and each ``javascript:`` link. The history page's own one script reads
    ``["<script>"]``."""
    reader = _Scripts()
    reader.feed(page)
    reader.close()
    return reader.found


# A history page's heading, as ``dashboard`` writes it: its words; where it heads a switched section's view, the
# switch's labels and the words after them; then its hint as the title and label of a ?, if it has one.
_PAGE_HEADING = re.compile(r'<h2>([^<]*?)(?: <span class="seg">((?:<label[^>]*>[^<]*</label>)+)</span>([^<]*?))?'
                           r'(?: <span class="help" tabindex="0" title="([^"]*)" aria-label="\4">\?</span>)?</h2>')


def page_headings(page: str) -> list[tuple[str, tuple[str, ...], str, str]]:
    """Every ``<h2>`` of a history page or its export, in order, unescaped, as (its words before the switch, the
    switch's words, its words after the switch, its hint); a heading of no switch has no switch's words and nothing
    after. A heading of any other shape is not read, so its count falls short of the page's ``<h2>``."""
    return [(unescape(before), tuple(unescape(word) for word in re.findall(r">([^<]*)</label>", labels)),
             unescape(after), unescape(hint)) for before, labels, after, hint in _PAGE_HEADING.findall(page)]


def laid_out(blocks) -> list:
    """The History window's ``blocks`` in the order the window lays them out: each switch in its place given as its
    every view's blocks, in the switch's order, since each view is laid out once, those not shown hidden."""
    return [inner for block in blocks
            for inner in ([b for view in block.views for b in view.blocks] if isinstance(block, Switch) else [block])]


def assistant_lines(message_id: str, t: float, session_id: str, *, model: str = "claude-opus-5-5",
                    outputs: tuple[int, ...] = (8, 120), input_tokens: int = 2, cache_read: int = 1000,
                    cache_write_1h: int = 500, cache_write_5m: int = 0, thinking: int = 40,
                    entrypoint: str = "claude-desktop", effort: str = "xhigh", agent_id: str | None = None,
                    speed: str = "standard", breakdown: bool = True) -> list[dict]:
    """The lines Claude Code writes for one response: one per content block, usage growing to its final value."""
    lines = []
    for index, output in enumerate(outputs):
        usage = {"input_tokens": input_tokens, "cache_creation_input_tokens": cache_write_1h + cache_write_5m,
                 "cache_read_input_tokens": cache_read, "output_tokens": output,
                 "output_tokens_details": {"thinking_tokens": thinking}, "speed": speed,
                 "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0}}
        if breakdown:
            usage["cache_creation"] = {"ephemeral_1h_input_tokens": cache_write_1h,
                                       "ephemeral_5m_input_tokens": cache_write_5m}
        line = {"type": "assistant", "timestamp": iso(t + index * 0.5), "sessionId": session_id,
                "entrypoint": entrypoint, "version": "2.1.299", "cwd": "D:\\Work\\Project", "isSidechain": bool(agent_id),
                "requestedModel": model, "effort": effort, "requestId": "req_" + message_id,
                "message": {"id": message_id, "model": model, "role": "assistant",
                            "content": [{"type": "text", "text": "…"}], "usage": usage}}
        if agent_id:
            line["agentId"] = agent_id
        lines.append(line)
    return lines


MANIFEST_COLUMNS = ("vendor", "subject", "account", "entry_id", "date", "status", "currency", "amount", "eur_equiv",
                    "eur_basis", "doc_type", "invoice_no", "receipt_no", "line_item", "service_period", "filename")


def bill(account: str, day: str, amount: float, *, plan: str | None = "ultra", kind: str = "subscription",
         period: str | None = None, currency: str = "EUR", reference: str | None = None) -> dict:
    """An entry of WindowTally's own bills file; ``period`` is "START..END"."""
    entry: dict = {"account": account, "date": day, "kind": kind, "amount": amount, "currency": currency}
    if plan is not None and kind == "subscription":
        entry["plan"] = plan
    if period:
        entry["start"], entry["end"] = period.split("..")
    if reference:
        entry["reference"] = reference
    return entry


def manifest_rows(account: str, entry_id: str, day: str, amount: str, line_item: str, period: str = "", *,
                  invoice: str, status: str = "paid", vendor: str = "Anthropic Claude",
                  currency: str = "EUR") -> list[dict]:
    """The rows a bill archive's manifest holds for one bill: its invoice and, when paid, its receipt."""
    base = {"vendor": vendor, "subject": "Personal", "account": account, "entry_id": entry_id, "date": day,
            "status": status, "currency": currency, "amount": amount,
            "eur_equiv": amount if status == "paid" else "0.00", "eur_basis": "native" if status == "paid" else "voided",
            "invoice_no": invoice, "line_item": line_item, "service_period": period}
    rows = [dict(base, doc_type="Invoice", receipt_no="", filename=f"{day}_{entry_id}_Invoice.pdf")]
    if status == "paid":
        rows.append(dict(base, doc_type="Receipt", receipt_no=f"R-{invoice}", filename=f"{day}_{entry_id}_Receipt.pdf"))
    return rows


def status_window(state: str = "running", percent: float | None = 82.0, resets: float | None = None,
                  as_of: float | None = None, estimated: bool = False, exhausts: float | None = None,
                  anchor_exact: bool | None = None) -> dict:
    """A window of status.json version 3 (windowtally/status_file.py)."""
    data = {"state": state, "percent": percent, "resetsAt": iso(resets) if resets else None,
            "asOf": iso(as_of) if as_of else None, "estimated": estimated,
            "exhaustsAt": iso(exhausts) if exhausts else None}
    if anchor_exact is not None:
        data["anchorExact"] = anchor_exact
    return data


def status_subscription(**changes) -> dict:
    """An account's subscription in status.json: Ultra, paid until 7 November, this month's plan time worth $161.29
    at list price."""
    data = {"state": "active", "plan": "ultra", "planName": "Ultra", "paidUntil": "2026-11-07", "daysLeft": 18,
            "renewSoon": False, "thisMonthListPrice": 161.29, "profilePlan": "ultra", "profileCheck": "matches"}
    data.update(changes)
    return data


def status_account(uuid: str, email: str, *, at: float, desktop: bool = True, cli: bool = True,
                   five_hour: dict | None = None, weekly: dict | None = None, plan: dict | None = None) -> dict:
    """An account of status.json as of ``at``: by default 82 % of its 5-hour window, 69 % of its week."""
    return {"uuid": uuid, "email": email, "label": email.split("@")[0], "isDesktop": desktop, "isCli": cli,
            "lastActivity": iso(at - 600),
            "fiveHour": five_hour or status_window(resets=at + 80 * 60, as_of=at - 60),
            "weekly": weekly or status_window("current", 69.0, at + 3 * 86400, as_of=at - 60, anchor_exact=True),
            "subscription": plan}


def status_document(accounts: list[dict], *, at: float, **changes) -> dict:
    """status.json version 3 written at ``at``, the first account in use and recommended, with this month's totals
    across the accounts, the plans' total summing the accounts' own and none while no account has a subscription. An
    account may be given in a broken shape, to test its refusal."""
    first = accounts[0].get("uuid") if accounts else None
    label = accounts[0].get("label", "") if accounts else ""
    plans = [a["subscription"].get("thisMonthListPrice") for a in accounts
             if isinstance(a, dict) and isinstance(a.get("subscription"), dict)]
    plans_total = round(sum(p for p in plans if isinstance(p, (int, float))), 2) if plans else None
    doc = {"v": 3, "generatedAt": iso(at), "desktopAccount": first, "cliAccount": first, "cliCondition": None,
           "sourceErrors": [],
           "recommended": {"account": first, "reason": f"{label} has room left.", "reliefAt": None, "reliefExact": False},
           "renewalReminderDays": None, "notificationsSilenced": False,
           "thisMonth": {"apiEquivalent": 1283.56, "plansAtListPrice": plans_total}, "accounts": accounts}
    doc.update(changes)
    return doc


def register_session(claude_home: Path, session_id: str, *, status: str = "busy", pid: int | None = None,
                     entrypoint: str = "claude-desktop", changed: float | None = None,
                     created: int | None = None) -> Path:
    """An entry of Claude Code's session registry (``windowtally.registry``) under ``claude_home``, as Claude Code 2.1
    writes one: by default this test's own process, a live one, at its real creation time, so the entry counts as a
    session of the desktop app at work. ``pid`` names another live process; ``changed`` is its status's last change;
    ``created`` gives the entry a creation time of its own, which for a process not created then makes it the file a
    process that ended left behind."""
    import os
    from windowtally.registry import WindowsProcesses
    pid = os.getpid() if pid is None else pid
    if created is None:
        created = WindowsProcesses().created(pid)
        if created is None:
            raise AssertionError(f"process {pid} is not running, so its registry entry would not count")
    data = {"pid": pid, "sessionId": session_id, "cwd": "C:\\work", "procStart": str(created), "kind": "interactive",
            "entrypoint": entrypoint, "status": status, "version": "2.1.321"}
    if changed is not None:
        data["statusUpdatedAt"] = data["updatedAt"] = int(changed * 1000)
    folder = claude_home / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{pid}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def bridge_line(session_id: str, owner: str, org: str) -> dict:
    return {"type": "bridge-session", "sessionId": session_id, "bridgeSessionId": "bridge_x", "lastSequenceNum": 0,
            "ownerAccountUuid": owner, "ownerOrganizationUuid": org}


def user_line(session_id: str, prompt_id: str, t: float, *, sidechain: bool = False) -> dict:
    return {"type": "user", "timestamp": iso(t), "sessionId": session_id, "promptId": prompt_id,
            "isSidechain": sidechain, "entrypoint": "claude-desktop", "message": {"role": "user", "content": "…"}}


class Machine:
    """A machine in a temporary folder; ``paths`` points WindowTally at it."""

    def __init__(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="windowtally-test-")
        root = Path(self._temp.name)
        self.paths = MachinePaths(claude_home=root / "claude", desktop_data=root / "desktop", data_dir=root / "data")
        self.paths.projects_dir.mkdir(parents=True)
        self.paths.accounts_dir.mkdir(parents=True)
        self.paths.desktop_data.mkdir(parents=True)

    def close(self) -> None:
        self._temp.cleanup()

    def add_account(self, uuid: str, email: str, org: str, *, organization_type: str = "claude_max",
                    tier: str = "default_claude_max_20x", fetched: float | None = None) -> None:
        folder = self.paths.accounts_dir / uuid
        folder.mkdir(parents=True, exist_ok=True)
        profile = {"accountUuid": uuid, "emailAddress": email, "organizationUuid": org,
                   "organizationName": f"{email}'s Organization", "organizationType": organization_type,
                   "organizationRateLimitTier": tier, "billingType": "stripe_subscription"}
        if fetched is not None:
            profile["profileFetchedAt"] = int(fetched * 1000)
        (folder / "oauthAccount.json").write_text(json.dumps(profile), encoding="utf-8")

    def bills_file(self, bills: list[dict], version: int = 1) -> Path:
        """WindowTally's own bills file."""
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.bills_file.write_text(json.dumps({"v": version, "bills": bills}), encoding="utf-8")
        return self.paths.bills_file

    def settings(self, data: dict) -> Path:
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.settings_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self.paths.settings_file

    def manifest(self, rows: list[dict], name: str = "_manifest.csv", columns: tuple[str, ...] = MANIFEST_COLUMNS) -> Path:
        """A bill archive's manifest beside the machine's folders."""
        path = self.paths.claude_home.parent / "archive" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def transcript(self, session_id: str, lines: list[dict], *, project: str = "D--Work-Project",
                   agent: str | None = None, append: bool = False, raw_tail: str = "") -> Path:
        folder = self.paths.projects_dir / project
        path = folder / session_id / "subagents" / f"agent-{agent}.jsonl" if agent else folder / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines) + raw_tail
        with path.open("a" if append else "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def app_history(self, samples: list[tuple[float, str, float, float]], version: int = 2) -> None:
        """Samples as (epoch seconds, organization, 5-hour %, weekly %)."""
        data = {"version": version, "samples": [{"t": int(t * 1000), "org": org, "u": {"fh": fh, "sd": sd}}
                                                for t, org, fh, sd in samples]}
        self.paths.plan_usage_history.write_text(json.dumps(data), encoding="utf-8")

    def reading(self, session_id: str, t: float, five_hour: tuple[float, float], weekly: tuple[float, float],
                version: int = 1) -> Path:
        """A plugin reading: each window as (percent, reset epoch)."""
        self.paths.readings_dir.mkdir(parents=True, exist_ok=True)
        path = self.paths.readings_dir / f"{session_id}.json"
        path.write_text(json.dumps({"v": version, "t": int(t * 1000), "sessionId": session_id, "windows": [
            {"kind": "five_hour", "percentUsed": five_hour[0], "resetsAt": iso(five_hour[1])},
            {"kind": "seven_day", "percentUsed": weekly[0], "resetsAt": iso(weekly[1])}]}), encoding="utf-8")
        return path

    def sync_events(self, events: list[tuple[float, str, str]], rotated: bool = False) -> None:
        path = self.paths.sync_events.with_name("events.jsonl.1") if rotated else self.paths.sync_events
        with path.open("a", encoding="utf-8") as handle:
            for t, kind, account in events:
                handle.write(json.dumps({"t": iso(t), "kind": kind, "account": account}) + "\n")

    def sync_log(self, lines: list[str]) -> None:
        with self.paths.sync_log.open("a", encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in lines))

    def watch_view(self, desktop: str | None, cli: str | None, condition: str | None = None,
                   at: float | None = None, *, signed_out: bool = False, running: bool = True) -> None:
        """The sync watcher's view, written at ``at`` (by default 2026-10-20 15:00 -05:00); ``signed_out``, of a desktop
        app at its sign-in page, as the watcher writes it then: no desktop account, and ``desktopSignedIn`` false;
        ``running`` false, of a desktop app that is not running: ``desktopRunning`` false."""
        written = iso(at) if at is not None else "2026-10-20T15:00:00.000-05:00"
        view = {"t": written, "desktopAccount": None if signed_out else desktop, "cliAccount": cli,
                "condition": condition}
        if signed_out:
            view["desktopSignedIn"] = False
        if not running:
            view["desktopRunning"] = False
        self.paths.sync_watch_state.write_text(json.dumps(view), encoding="utf-8")
