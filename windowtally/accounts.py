"""The account registry, read from the account sync's store.

The sync keeps one folder per account under ``~/.claude/accounts/<accountUuid>/``. Only ``oauthAccount.json`` is
read here: the account's profile as Claude Code recorded it (UUID, e-mail, organization, its type and rate-limit
tier, and when Claude Code fetched the profile). The sealed credentials beside it are never opened.

The profile names only the plan the account is on now (``organizationType`` ``claude_pro`` or ``claude_max``, the
latter's rate-limit tier ``default_claude_max_5x`` for Max 5x or ``default_claude_max_20x`` for Ultra, as Claude
Code's own bundle spells them); what a subscription cost comes from the user's bills (``bills``).

An account is shown by its ``label``: the name the user gave it in WindowTally's settings (``settings``), else its
``default_label``, derived from its e-mail. The user's name is for showing only — every action names an account by its
UUID — so it is applied where the accounts are read for showing (``named``), never stored in the ledger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence, TypeVar

T = TypeVar("T")


def default_label(uuid: str, email: str | None) -> str:
    """An account's name where the user gave it none: the e-mail's local part, else a short UUID."""
    if email and "@" in email:
        return email.split("@", 1)[0]
    return email or uuid[:8]


def name_key(name: str) -> tuple[str, str]:
    """The order of accounts by name: case-insensitively, then by the name itself, so the order is total."""
    return name.casefold(), name


@dataclass(frozen=True)
class Account:
    uuid: str
    email: str | None = None
    org_uuid: str | None = None
    org_name: str | None = None
    rate_limit_tier: str | None = None
    # Read from the profile only; the ledger's copy of the registry does not keep them.
    organization_type: str | None = None
    profile_fetched_at: float | None = None   # epoch seconds
    name: str | None = None                   # the user's own name for the account, from WindowTally's settings

    @property
    def default_label(self) -> str:
        """The name derived from the account itself, whatever the user named it."""
        return default_label(self.uuid, self.email)

    @property
    def label(self) -> str:
        """The name shown everywhere: the user's own where set, else ``default_label``."""
        return self.name or self.default_label


def named(accounts: Mapping[str, Account], names: Mapping[str, str]) -> dict[str, Account]:
    """``accounts`` by UUID, each carrying the user's name for it where ``names`` gives one."""
    return {uuid: replace(a, name=names[uuid]) if uuid in names else a for uuid, a in accounts.items()}


def arranged(items: Iterable[T], order: Sequence[str], uuid_of: Callable[[T], str],
             name_of: Callable[[T], str]) -> list[T]:
    """``items`` in the user's order: those ``order`` lists, as it lists them, then the rest by name (``name_key``),
    accounts shown by one name by UUID, so that every reader, the window's arrangement included, ties them alike. A
    listed UUID no item has is passed over."""
    items = list(items)   # read twice below
    place = {uuid: index for index, uuid in enumerate(order)}
    listed = sorted((i for i in items if uuid_of(i) in place), key=lambda i: place[uuid_of(i)])
    rest = sorted((i for i in items if uuid_of(i) not in place), key=lambda i: (name_key(name_of(i)), uuid_of(i)))
    return listed + rest


def load_registry(accounts_dir: Path) -> tuple[dict[str, Account], list[str]]:
    """Every stored account by UUID, and a warning for each folder whose profile could not be read."""
    accounts: dict[str, Account] = {}
    warnings: list[str] = []
    if not accounts_dir.is_dir():
        return accounts, warnings
    for folder in sorted(accounts_dir.iterdir()):
        profile = folder / "oauthAccount.json"
        if not folder.is_dir() or not profile.is_file():
            continue
        try:
            data = json.loads(profile.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            warnings.append(f"Unreadable account profile {profile}: {exc}")
            continue
        uuid = str(data.get("accountUuid") or folder.name).lower()
        fetched = data.get("profileFetchedAt")
        accounts[uuid] = Account(
            uuid=uuid,
            email=data.get("emailAddress"),
            org_uuid=(data.get("organizationUuid") or None),
            org_name=data.get("organizationName"),
            rate_limit_tier=data.get("organizationRateLimitTier") or data.get("userRateLimitTier"),
            organization_type=data.get("organizationType") or None,
            profile_fetched_at=fetched / 1000.0 if isinstance(fetched, (int, float)) and fetched > 0 else None,
        )
    return accounts, warnings


def by_org(accounts: dict[str, Account]) -> dict[str, str]:
    """Organization UUID -> account UUID, for sources keyed by organization (the app's samples)."""
    return {a.org_uuid.lower(): a.uuid for a in accounts.values() if a.org_uuid}


def by_email(accounts: dict[str, Account]) -> dict[str, str]:
    """Lower-cased e-mail -> account UUID, for sources that name accounts by e-mail (the sync log)."""
    return {a.email.lower(): a.uuid for a in accounts.values() if a.email}
