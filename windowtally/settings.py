"""``settings.json`` — what the user tells WindowTally that no file on the machine says: where else bills are kept,
whether the band reminds of a subscription about to end, whether WindowTally's notifications are silenced, whether the
computer is kept awake while Claude Code works, and the order and names the accounts are shown in, and which accounts are
not shown.

Contract (version 1), in WindowTally's data folder, written by ``python -m windowtally bills source`` and
``bills remind``, by the window (``windowtally_gui``) or by hand:

    {"v": 1,
     "billSources": [{"format": "manifest", "path": "E:\\Paperwork\\bill-manifest.csv"}],
     "renewalReminderDays": 3,
     "silenceNotifications": true,
     "keepAwakeOff": true,
     "accountOrder": ["<uuid>", "<uuid>"],
     "accountNames": {"<uuid>": "Work"},
     "hiddenAccounts": ["<uuid>"]}

``billSources`` names bill files beyond WindowTally's own ``bills.json``, which is read whenever it exists: ``format`` is
``bills`` (a file in WindowTally's own format, ``bills``) or ``manifest`` (a bill archive's manifest, ``bills_manifest``);
a relative ``path`` is taken from the data folder. ``renewalReminderDays`` turns the band's renewal reminder on — an
account whose recorded subscription ends within that many days is tagged there — and is absent or null while the
reminder is off. It is off by default: a subscription that renews by itself needs no reminder, and nothing on the
machine says which kind a subscription is. ``silenceNotifications`` true silences WindowTally's notifications: the window
raises no Windows notification and the desktop plugin no limit toast, the service carrying the setting to the plugin
in status.json; absent or false they are raised. ``keepAwakeOff`` true turns off the service's keep-awake
(``keep_awake``); absent or false, the service keeps the computer awake while a Claude Code session works, which it reads
again within seconds of a change.

``accountOrder`` is the user's order of the accounts, by UUID, each once: every surface that lists the accounts shows
them in it (``status_file``), an account it does not list after the listed ones by name, a listed UUID no account has
passed over. Absent, the accounts stand by name. ``accountNames`` gives an account a name of the user's own, by UUID,
shown wherever the account's name is: at most ``NAME_LIMIT`` characters (code points, so the band, which cuts a name
past 16 grapheme clusters, never cuts one), no control or format character, no space before or after, and no two names
the same, case aside. An account it does not name is shown by its e-mail's local part (``accounts.default_label``).
``hiddenAccounts`` lists, by UUID, each once, the accounts the user hid: no surface lists one while neither the desktop
app nor the CLI uses it, and none is recommended (``status_file``, ``limits.recommend``); the history keeps them. A
listed UUID no account has is kept. The window writes the three together, onto what the file holds when it writes
(``edit_account_arrangement``). Every key but ``v`` is optional; ``keepAwakeOff`` and the last three were added
without a change of version, each named so that its absence is the default, which a reader that does not know it
takes.

A file in another version, with a key this version does not define, or with a value of the wrong kind is refused as a
whole, every problem named; a misspelt key would otherwise be a setting that silently does not take effect.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .files import editing, write_text_atomically

SETTINGS_VERSION = 1
SOURCE_FORMATS = ("bills", "manifest")
REMINDER_DAYS_LIMITS = (1, 31)
NAME_LIMIT = 16   # characters an account's name holds at most: what the band shows whole
_KEYS = ("v", "billSources", "renewalReminderDays", "silenceNotifications", "keepAwakeOff", "accountOrder",
         "accountNames", "hiddenAccounts")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Unicode categories a name may not hold: control and format characters, surrogates, line and paragraph separators —
# characters that show as nothing, or break the line a name stands on.
_HIDDEN = ("Cc", "Cf", "Cs", "Zl", "Zp")


class SettingsError(ValueError):
    """The settings file is not version 1 of the contract; the message names every problem."""


@dataclass(frozen=True)
class BillSource:
    format: str     # one of SOURCE_FORMATS
    path: Path


@dataclass(frozen=True)
class Settings:
    bill_sources: tuple[BillSource, ...] = ()
    renewal_reminder_days: int | None = None
    silence_notifications: bool = False
    keep_awake_off: bool = False
    account_order: tuple[str, ...] = ()                 # UUIDs, each once
    account_names: tuple[tuple[str, str], ...] = ()     # (UUID, name), each UUID once
    hidden_accounts: tuple[str, ...] = ()               # UUIDs, each once

    @property
    def names(self) -> dict[str, str]:
        """The user's names for the accounts, by UUID."""
        return dict(self.account_names)

    @property
    def hidden(self) -> frozenset[str]:
        """The accounts the user hid, by UUID."""
        return frozenset(self.hidden_accounts)


def name_problem(name: str) -> str | None:
    """Why ``name`` cannot be an account's name, in words; None when it can."""
    if not name:
        return "it is empty"
    if name != name.strip():
        return "it starts or ends with a space"
    if len(name) > NAME_LIMIT:
        return f"it is longer than {NAME_LIMIT} characters"
    hidden = next((c for c in name if unicodedata.category(c) in _HIDDEN), None)
    if hidden is not None:
        return f"it holds U+{ord(hidden):04X}, a character that shows as nothing or breaks the line"
    return None


def _account_list(value: object, key: str) -> tuple[tuple[str, ...], list[str]]:
    """A list of account UUIDs, each once, under ``key`` — ``accountOrder`` or ``hiddenAccounts`` — as UUIDs in lower
    case, and every problem with it."""
    if not isinstance(value, list):
        return (), [f"{key} is not a list"]
    uuids: list[str] = []
    problems: list[str] = []
    for index, entry in enumerate(value, start=1):
        uuid = entry.lower() if isinstance(entry, str) else None
        if uuid is None or not _UUID.match(uuid):
            problems.append(f"{key} entry {index} is not an account UUID")
        elif uuid in uuids:
            problems.append(f"{key} entry {index} repeats {uuid}")
        else:
            uuids.append(uuid)
    return tuple(uuids), problems


def _account_order(value: object) -> tuple[tuple[str, ...], list[str]]:
    """``accountOrder`` as UUIDs in lower case, and every problem with it."""
    return _account_list(value, "accountOrder")


def _hidden_accounts(value: object) -> tuple[tuple[str, ...], list[str]]:
    """``hiddenAccounts`` as UUIDs in lower case, and every problem with it."""
    return _account_list(value, "hiddenAccounts")


def _account_names(value: object) -> tuple[tuple[tuple[str, str], ...], list[str]]:
    """``accountNames`` as (UUID in lower case, name) pairs, and every problem with it."""
    if not isinstance(value, dict):
        return (), ["accountNames is not an object"]
    names: dict[str, str] = {}
    seen: dict[str, str] = {}   # casefolded name -> the UUID that has it
    problems: list[str] = []
    for key, name in value.items():
        uuid = key.lower() if isinstance(key, str) else ""
        if not _UUID.match(uuid):
            problems.append(f"accountNames names {key!r}, which is not an account UUID")
            continue
        if uuid in names:
            problems.append(f"accountNames names {uuid} twice")
            continue
        problem = name_problem(name) if isinstance(name, str) else "it is not text"
        if problem:
            problems.append(f"the name of {uuid} cannot be used: {problem}")
            continue
        folded = name.casefold()
        if folded in seen:
            problems.append(f"the name {name!r} of {uuid} is also the name of {seen[folded]}, case aside")
            continue
        seen[folded] = uuid
        names[uuid] = name
    return tuple(names.items()), problems


def same_file(a: Path, b: Path) -> bool:
    """Whether two paths name one file however they are spelt: relative or absolute, in any case, through '..'."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _source_path(text: str, settings_path: Path) -> Path:
    path = Path(text).expanduser()
    return Path(os.path.abspath(path if path.is_absolute() else settings_path.parent / path))


def load_settings(path: Path) -> Settings:
    """The settings, or the defaults when the file does not exist."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return Settings()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SettingsError(f"{path} is not JSON ({exc})") from None
    if not isinstance(data, dict):
        raise SettingsError(f"{path} is not a JSON object")
    if data.get("v") != SETTINGS_VERSION:
        raise SettingsError(f"{path} is version {data.get('v')!r}; this version of WindowTally reads version {SETTINGS_VERSION}")
    problems = [f"unknown key {key!r}" for key in data if key not in _KEYS]
    sources: list[BillSource] = []
    listed = data.get("billSources", [])
    if not isinstance(listed, list):
        problems.append("billSources is not a list")
        listed = []
    for index, entry in enumerate(listed, start=1):
        if not isinstance(entry, dict) or set(entry) != {"format", "path"}:
            problems.append(f"bill source {index} is not an object with exactly a format and a path")
            continue
        if entry["format"] not in SOURCE_FORMATS:
            problems.append(f"bill source {index} has the format {entry['format']!r}, not one of {', '.join(SOURCE_FORMATS)}")
            continue
        if not isinstance(entry["path"], str) or not entry["path"].strip():
            problems.append(f"bill source {index} has no path")
            continue
        source = BillSource(entry["format"], _source_path(entry["path"].strip(), path))
        if any(same_file(s.path, source.path) for s in sources):
            problems.append(f"bill source {index} repeats {source.path}")
            continue
        sources.append(source)
    days = data.get("renewalReminderDays")
    low, high = REMINDER_DAYS_LIMITS
    if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not low <= days <= high):
        problems.append(f"renewalReminderDays is {days!r}, not null or a whole number of days from {low} to {high}")
        days = None
    silence = data.get("silenceNotifications", False)
    if not isinstance(silence, bool):
        problems.append(f"silenceNotifications is {silence!r}, not true or false")
    awake_off = data.get("keepAwakeOff", False)
    if not isinstance(awake_off, bool):
        problems.append(f"keepAwakeOff is {awake_off!r}, not true or false")
    order, order_problems = _account_order(data.get("accountOrder", []))
    names, name_problems = _account_names(data.get("accountNames", {}))
    hidden, hidden_problems = _hidden_accounts(data.get("hiddenAccounts", []))
    problems += order_problems + name_problems + hidden_problems
    if problems:
        raise SettingsError(f"{path}: " + "; ".join(problems))
    return Settings(bill_sources=tuple(sources), renewal_reminder_days=days, silence_notifications=silence,
                    keep_awake_off=awake_off, account_order=order, account_names=names, hidden_accounts=hidden)


def save_settings(path: Path, settings: Settings) -> None:
    """Writes the settings whole, replacing the file atomically, in UTF-8 whatever the console's code page."""
    data: dict = {"v": SETTINGS_VERSION}
    if settings.bill_sources:
        data["billSources"] = [{"format": s.format, "path": str(s.path)} for s in settings.bill_sources]
    if settings.renewal_reminder_days is not None:
        data["renewalReminderDays"] = settings.renewal_reminder_days
    if settings.silence_notifications:
        data["silenceNotifications"] = True
    if settings.keep_awake_off:
        data["keepAwakeOff"] = True
    if settings.account_order:
        data["accountOrder"] = list(settings.account_order)
    if settings.account_names:
        data["accountNames"] = dict(settings.account_names)
    if settings.hidden_accounts:
        data["hiddenAccounts"] = list(settings.hidden_accounts)
    write_text_atomically(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def set_renewal_reminder(path: Path, days: int | None) -> Settings:
    """Turns the renewal reminder on at ``days`` days, or off with None, keeping every other setting; the settings
    written. SettingsError when the file cannot be read; ValueError for a number of days outside the limits."""
    low, high = REMINDER_DAYS_LIMITS
    if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not low <= days <= high):
        raise ValueError(f"the reminder takes a whole number of days from {low} to {high}, not {days!r}")
    with editing(path):
        settings = replace(load_settings(path), renewal_reminder_days=days)
        save_settings(path, settings)
    return settings


def set_notifications_silenced(path: Path, silenced: bool) -> Settings:
    """Silences WindowTally's notifications, or lets them be raised again, keeping every other setting; the settings
    written. SettingsError when the file cannot be read."""
    with editing(path):
        settings = replace(load_settings(path), silence_notifications=silenced)
        save_settings(path, settings)
    return settings


def keeps_awake(path: Path) -> bool | None:
    """Whether the settings let the service keep the computer awake while Claude Code works: True unless they turn it
    off; None where they cannot be read, which the service takes for True, the default, and the window shows so."""
    try:
        return not load_settings(path).keep_awake_off
    except (ValueError, OSError):   # SettingsError is a ValueError
        return None


def set_keep_awake(path: Path, on: bool) -> Settings:
    """Turns the service's keep-awake on, the default, or off, keeping every other setting; the settings written.
    SettingsError when the file cannot be read."""
    with editing(path):
        settings = replace(load_settings(path), keep_awake_off=not on)
        save_settings(path, settings)
    return settings


def set_account_arrangement(path: Path, order: Sequence[str], names: Mapping[str, str],
                            hidden: Sequence[str] | None = None) -> Settings:
    """Sets the accounts' order and the user's names for them, together and whole — an empty order is the order by
    name, an account ``names`` leaves out is shown by its e-mail — and, where ``hidden`` is given, the accounts hidden,
    keeping every other setting; the settings written. SettingsError when the file cannot be read; ValueError naming
    every problem with an order, names or hidden accounts this version refuses, the file then left as it was. It
    replaces whatever the file holds of them: a writer that shows the user what it read, as the window does, writes
    through ``edit_account_arrangement``, so a change made meanwhile is not undone."""
    return edit_account_arrangement(path, lambda _current: (order, names) if hidden is None else (order, names, hidden))


Arranged = tuple[Sequence[str], Mapping[str, str]] | tuple[Sequence[str], Mapping[str, str], Sequence[str]]


def edit_account_arrangement(path: Path, edit: Callable[[Settings], Arranged]) -> Settings:
    """Sets the accounts' order and names, and the accounts hidden where ``edit`` gives them, to what ``edit`` makes of
    the settings as they stand: the order and the names, then the hidden accounts, which a pair leaves as the file holds
    them. Read under the file's edit lock so that no other change lands between that reading and the write; every
    other setting kept, the settings written. ``edit`` raising ValueError writes nothing. SettingsError when the file
    cannot be read; ValueError naming every problem with an order, names or hidden accounts this version refuses, the
    file then left as it was."""
    with editing(path):
        current = load_settings(path)
        arranged = edit(current)
        order, names = arranged[0], arranged[1]
        arranged_order, order_problems = _account_order(list(order))
        arranged_names, name_problems = _account_names(dict(names))
        arranged_hidden, hidden_problems = (_hidden_accounts(list(arranged[2])) if len(arranged) == 3
                                            else (current.hidden_accounts, []))
        if order_problems or name_problems or hidden_problems:
            raise ValueError("; ".join(order_problems + name_problems + hidden_problems))
        settings = replace(current, account_order=arranged_order, account_names=arranged_names,
                           hidden_accounts=arranged_hidden)
        save_settings(path, settings)
    return settings
