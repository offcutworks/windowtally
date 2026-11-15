"""The browser extension's native-messaging host: it writes the usage figures claude.ai's page received where the
service reads them, and its registration with Chrome.

The extension (``extension/`` beside this package) reads the 5-hour and weekly figures from the usage response
claude.ai's own page receives — it sends no request and reads no credential — and hands them to Chrome's native
messaging, which starts this host for each message and ends it after the answer. A message is a 32-bit length in the
machine's byte order and that many bytes of UTF-8 JSON on standard input; the answer goes back the same way on
standard output. WindowTally opens no listening port.

Message and file (version 1) — the extension sends a reading, and the host keeps one file per organization,
``<data>/browser/<organizationUuid>.json``, overwritten with the latest reading the page received:

    {"v": 1, "t": <epoch ms the page received the figures>, "org": "<organization UUID>",
     "windows": [{"kind": "five_hour", "percentUsed": 34, "resetsAt": "2027-03-09T14:00:00.250000+00:00"},
                 {"kind": "seven_day", "percentUsed": 61, "resetsAt": "2027-03-12T09:00:00.250000+00:00"}]}

The organization is the one the page's usage request names, the one an account's profile records, so the reading
names its account as the desktop app's samples do. ``percentUsed`` and ``resetsAt`` are the response's ``utilization``
and ``resets_at``; ``resetsAt`` may be null. The answer is ``{"ok": true}``, or ``{"ok": false, "error": "<why>"}``
with nothing written. A message is checked whole before anything is written: a page can post what it likes, and the
organization names a file.

A reading may also carry the week's use by product, where the page's response had it (``products``):

    "weeklyByProduct": {"asOf": "2027-03-09T11:20:40.500000+00:00",
                        "windowStartedAt": "2027-03-05T09:00:00.250000+00:00",
                        "rows": [{"key": "claude_code", "name": "Claude Code", "percent": 82},
                                 {"key": "chat", "name": "Chats", "percent": 18}]}

And it may carry the week's per-model windows, where the page's response had them — a weekly window of one model's
own, inside the account's weekly window, as Fable's is:

    "weeklyScoped": [{"name": "Fable", "percentUsed": 21, "resetsAt": "2027-03-12T09:00:00.250000+00:00",
                      "allowanceOfWeekly": 50}]

``name`` is the model's name as the page shows it, ``percentUsed`` and ``resetsAt`` the window's as above, and
``allowanceOfWeekly`` the share of the weekly window the model's allowance is, in percent, or null where the response
did not say.

Each is an optional key of version 1, so either side may lack it: a host that predates one builds its file from the
keys it checks and drops it, and a message without it is the reading it always was. Each is checked on its own
(``by_product_from``, ``scoped_from``) and never costs the windows: one this host cannot read is left out of the file,
the windows written, and the answer says why (``checked_reading``), ``{"ok": true, "dropped": "<why>"}``.

Registration: Chrome finds the host through one key in the user's own part of the registry,
``HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\windowtally.browser``, whose default value names the host's
manifest in ``<data>/browser-host``; the manifest names the launcher beside it and the one extension allowed to start
the host, by the ID Chrome derives from the public key in the extension's manifest. The launcher runs the console
interpreter on the installed copy of this package: Chrome talks to the host over its standard streams, which a
windowless interpreter may not have, and starts it with its console hidden. It names the readings folder of the data
folder it was registered for, so a registration made for a relocated data folder writes there.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import struct
import sys
from pathlib import Path
from typing import BinaryIO, Protocol

from .files import write_text_atomically
from .paths import MachinePaths
from .timeutil import parse_iso

READING_VERSION = 1
KINDS = ("five_hour", "seven_day")
BY_PRODUCT = "weeklyByProduct"
SCOPED = "weeklyScoped"
MAX_PRODUCTS = 32     # claude.ai lists four; far more is not its page's breakdown
MAX_SCOPED = 8        # claude.ai lists one; far more is not its page's list of per-model windows
MAX_NAME = 64
HOST_NAME = "windowtally.browser"
EXTENSION_ID = "nhabafmhfilijckoeeigflifdjmaicbp"
REGISTRY_KEY = r"Software\Google\Chrome\NativeMessagingHosts" + "\\" + HOST_NAME
LAUNCHER_NAME = "host.cmd"
MANIFEST_NAME = HOST_NAME + ".json"
MAX_MESSAGE = 64 * 1024   # a reading is a few hundred bytes; anything far larger is not one

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_PRODUCT_KEY = re.compile(r"^[a-z0-9_]{1,64}$")
_LENGTH = struct.Struct("=I")


class ReadingError(ValueError):
    """A message that is not a reading this host writes."""


# --- the reading ------------------------------------------------------------------------------------------------

def reading_from(message: object) -> dict:
    """The file a message becomes, built from its checked fields alone; ReadingError where it is not a reading."""
    return checked_reading(message)[0]


def checked_reading(message: object) -> tuple[dict, str | None]:
    """The file a message becomes, and why its ``weeklyByProduct`` or its ``weeklyScoped`` was left out of it — None
    where it had neither or both were kept; ReadingError where the message is not a reading."""
    if not isinstance(message, dict) or message.get("v") != READING_VERSION:
        version = message.get("v") if isinstance(message, dict) else None
        raise ReadingError(f"version {version!r}, expected {READING_VERSION}")
    org = message.get("org")
    if not isinstance(org, str) or not _UUID.match(org.lower()):
        raise ReadingError("org is not an organization UUID")
    t = message.get("t")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 < t < 1e14:
        raise ReadingError("t is not a time in epoch milliseconds")
    windows = message.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ReadingError("windows is not a list of windows")
    kept, seen = [], set()
    for window in windows:
        if not isinstance(window, dict) or window.get("kind") not in KINDS or window["kind"] in seen:
            raise ReadingError("a window is not one five_hour or seven_day window")
        percent, resets = window.get("percentUsed"), window.get("resetsAt")
        if not _percentage(percent):
            raise ReadingError(f"{window['kind']} percentUsed is not a percentage")
        if resets is not None and not isinstance(resets, str):
            raise ReadingError(f"{window['kind']} resetsAt is not a time")
        seen.add(window["kind"])
        kept.append({"kind": window["kind"], "percentUsed": percent, "resetsAt": resets})
    reading = {"v": READING_VERSION, "t": t, "org": org.lower(), "windows": kept}
    dropped = []
    for key, check in ((BY_PRODUCT, by_product_from), (SCOPED, scoped_from)):
        if key not in message:
            continue
        try:
            reading[key] = check(message[key])
        except ReadingError as exc:
            dropped.append(str(exc))   # the windows stand without it
    return reading, "; ".join(dropped) or None


def _percentage(value: object) -> bool:
    """Whether a value is a percentage a reading may carry: a finite number, not a flag, never below nothing."""
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def by_product_from(value: object) -> dict:
    """A reading's ``weeklyByProduct`` built from its checked fields alone; ReadingError where it is not one."""
    if not isinstance(value, dict):
        raise ReadingError("weeklyByProduct is not an object")
    as_of, start = value.get("asOf"), value.get("windowStartedAt")
    if parse_iso(as_of) is None:
        raise ReadingError("weeklyByProduct asOf is not a time")
    if parse_iso(start) is None:
        raise ReadingError("weeklyByProduct windowStartedAt is not a time")
    rows = value.get("rows")
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_PRODUCTS:
        raise ReadingError("weeklyByProduct rows is not a list of products")
    kept, seen = [], set()
    for row in rows:
        key = row.get("key") if isinstance(row, dict) else None
        if not isinstance(key, str) or not _PRODUCT_KEY.match(key) or key in seen:
            raise ReadingError("a product's key is not one lowercase name of its own")
        name, percent = row.get("name"), row.get("percent")
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
            raise ReadingError(f"product {key} has no name to show")
        if not _percentage(percent):
            raise ReadingError(f"product {key} percent is not a percentage")
        seen.add(key)
        kept.append({"key": key, "name": name.strip(), "percent": percent})
    return {"asOf": as_of, "windowStartedAt": start, "rows": kept}


def scoped_from(value: object) -> list[dict]:
    """A reading's ``weeklyScoped`` built from its checked fields alone; ReadingError where it is not one."""
    if not isinstance(value, list) or not 0 < len(value) <= MAX_SCOPED:
        raise ReadingError("weeklyScoped is not a list of per-model windows")
    kept, seen = [], set()
    for row in value:
        name = row.get("name") if isinstance(row, dict) else None
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or name.strip() in seen:
            raise ReadingError("a per-model window has no name of its own to show")
        name = name.strip()
        percent, resets, allowance = row.get("percentUsed"), row.get("resetsAt"), row.get("allowanceOfWeekly")
        if not _percentage(percent):
            raise ReadingError(f"per-model window {name} percentUsed is not a percentage")
        if resets is not None and parse_iso(resets) is None:
            raise ReadingError(f"per-model window {name} resetsAt is not a time")
        if allowance is not None and not (_percentage(allowance) and 0 < allowance <= 100):
            raise ReadingError(f"per-model window {name} allowanceOfWeekly is not a share of the weekly window")
        seen.add(name)
        kept.append({"name": name, "percentUsed": percent, "resetsAt": resets, "allowanceOfWeekly": allowance})
    return kept


def write_reading(browser_dir: Path, reading: dict) -> Path:
    """Writes a reading ``reading_from`` built over its organization's file; the file's path."""
    path = browser_dir / f"{reading['org']}.json"
    write_text_atomically(path, json.dumps(reading, separators=(",", ":")))
    return path


# --- native messaging -------------------------------------------------------------------------------------------

def read_message(stream: BinaryIO) -> object | None:
    """The next message, or None at the end of the stream. ReadingError for a frame that is not one."""
    header = stream.read(_LENGTH.size)
    if not header:
        return None
    if len(header) < _LENGTH.size:
        raise ReadingError("the stream ended inside a message's length")
    (length,) = _LENGTH.unpack(header)
    if length > MAX_MESSAGE:
        raise ReadingError(f"a message of {length} bytes is not a reading")
    body = stream.read(length)
    if len(body) < length:
        raise ReadingError("the stream ended inside a message")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReadingError(f"the message is not JSON: {exc}") from None


def write_message(stream: BinaryIO, message: dict) -> None:
    body = json.dumps(message).encode("utf-8")
    stream.write(_LENGTH.pack(len(body)) + body)
    stream.flush()


def serve(stdin: BinaryIO, stdout: BinaryIO, browser_dir: Path) -> int:
    """Answers every message until the stream ends; a frame that cannot be read is answered and ends the session,
    since what follows it cannot be told apart. The exit status is 0 unless a frame could not be read."""
    while True:
        try:
            message = read_message(stdin)
        except ReadingError as exc:
            write_message(stdout, {"ok": False, "error": str(exc)})
            return 1
        if message is None:
            return 0
        try:
            reading, dropped = checked_reading(message)
            write_reading(browser_dir, reading)
        except (ReadingError, OSError) as exc:
            write_message(stdout, {"ok": False, "error": str(exc)})
            continue
        write_message(stdout, {"ok": True} if dropped is None else {"ok": True, "dropped": dropped})


def main(argv: list[str]) -> int:
    """What the launcher runs: its first argument is the readings folder; Chrome's own arguments after it — the
    extension's origin, the parent window — are not needed."""
    if len(argv) < 2:
        print("usage: python -m windowtally.browser_host <readings folder> [Chrome's arguments]", file=sys.stderr)
        return 2
    if sys.platform == "win32":
        import msvcrt
        for stream in (sys.stdin, sys.stdout):
            msvcrt.setmode(stream.fileno(), os.O_BINARY)
    return serve(sys.stdin.buffer, sys.stdout.buffer, Path(argv[1]))


# --- registration -----------------------------------------------------------------------------------------------

class Registry(Protocol):
    """The default value of a key under HKEY_CURRENT_USER: all the registration needs."""

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class UserRegistry:
    """The user's own part of the Windows registry. A process inside the Claude desktop app may have its writes there
    land in the app's private view of the registry, as its AppData writes do, where Chrome never looks: install.ps1
    therefore registers from a task of its own."""

    def get(self, key: str) -> str | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "")
        except FileNotFoundError:
            return None
        return str(value)

    def set(self, key: str, value: str) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, value)

    def delete(self, key: str) -> None:
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def extension_id(public_key: str) -> str:
    """The ID Chrome gives an extension whose manifest carries ``public_key`` (base64 DER): the first 128 bits of the
    key's SHA-256, each hexadecimal digit written as a letter from a to p."""
    digest = hashlib.sha256(base64.b64decode(public_key)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(digit, 16)) for digit in digest)


def launcher_text(python: Path, app_dir: Path, browser_dir: Path) -> str:
    """The launcher Chrome runs: the console interpreter on the package in ``app_dir``, writing into ``browser_dir``.
    cmd.exe reads a batch file in the console's code page, so the file is UTF-8 and switches the console to it before
    naming a path; a ``%`` would be expanded and a ``"`` would end the quoting, so a path holding either is refused."""
    for path in (python, app_dir, browser_dir):
        if "%" in str(path) or '"' in str(path):
            raise ValueError(f"{path} holds a character a batch file cannot quote")
    return "\r\n".join(["@echo off", "chcp 65001 >nul", f'cd /d "{app_dir}"',
                        f'"{python}" -m windowtally.browser_host "{browser_dir}" %*', ""])


def host_manifest(launcher: Path) -> dict:
    return {"name": HOST_NAME, "description": "WindowTally: writes the usage figures the browser extension reads",
            "path": str(launcher), "type": "stdio", "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"]}


def register(paths: MachinePaths, python: Path, app_dir: Path, registry: Registry | None = None) -> Path:
    """Writes the launcher and the host's manifest into WindowTally's data folder and points Chrome's key at the manifest;
    the manifest's path. Run again, it replaces all three."""
    registry = UserRegistry() if registry is None else registry
    folder = paths.browser_host_dir
    folder.mkdir(parents=True, exist_ok=True)
    launcher, manifest = folder / LAUNCHER_NAME, folder / MANIFEST_NAME
    launcher.write_bytes(launcher_text(python, app_dir, paths.browser_dir).encode("utf-8"))
    write_text_atomically(manifest, json.dumps(host_manifest(launcher), indent=2) + "\n")
    registry.set(REGISTRY_KEY, str(manifest))
    return manifest


def unregister(paths: MachinePaths, registry: Registry | None = None) -> None:
    """Removes Chrome's key, then the launcher and the manifest; whatever is already gone is passed over."""
    registry = UserRegistry() if registry is None else registry
    registry.delete(REGISTRY_KEY)
    for name in (LAUNCHER_NAME, MANIFEST_NAME):
        try:
            (paths.browser_host_dir / name).unlink()
        except FileNotFoundError:
            pass
    try:
        paths.browser_host_dir.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main(sys.argv))
