"""What the window offers for switching accounts, and what asking for it leads to. No toolkit.

Two things switch: the desktop app (the account it is signed in to) and the CLI. While the sync's switch "the CLI
follows the desktop app" is on, switching the app switches the CLI with it, so a card offers one button, "Switch
here"; while it is off, the two switch apart and a card offers one button for each. A button is left out, not greyed,
on the card of the account the client already uses, and every button of the desktop app is left out while one-click
switching is off. A desktop app at its sign-in page uses no account, so every card offers it, the account it was
signed out of included: switching back to that account is how an add of an account is called off. The recommended
account's first button is the one accent of the window, the one filled button any of WindowTally's windows shows.

The cards, the Accounts menu and the tray menu all take their offers from here, from one status and one reading of
the two switches, so they never disagree, and list the accounts in status.json's order, the one order of WindowTally. The
switches are shown as the user last set them until a status written after the change says the same
(``switches_to_show``): the service rewrites the status only after a pass.

Asking to switch the app leads to one of three things (``plan_app_switch``): the switch itself; the question whether
to go on, while Code sessions are working, since closing the client ends them and the client's own prompt is bypassed
by the way the sync closes it; or an explanation, when WindowTally holds no desktop login of the account to put back.
Where the account the app leaves has sessions to go on with on the other (``carry_model``), the window asks which to
carry in place of the question, asking it there too.
"""

from __future__ import annotations

from dataclasses import dataclass

from .status_model import Account, Status

APP, CLI = "app", "cli"

# What asking to switch the app leads to.
RUN, CONFIRM_SESSIONS, NEEDS_LOGIN = "run", "confirm-sessions", "needs-login"


@dataclass(frozen=True)
class Switches:
    """The two switches of the account sync: the CLI follows the desktop app's account, and the desktop app can be
    switched in one click."""

    follows: bool = True
    one_click: bool = True


@dataclass(frozen=True)
class SwitchButton:
    client: str          # APP | CLI
    text: str
    accent: bool


@dataclass(frozen=True)
class SwitchEntry:
    """An account a menu offers to switch a client to."""

    client: str
    uuid: str
    label: str


@dataclass(frozen=True)
class Plan:
    kind: str            # RUN | CONFIRM_SESSIONS | NEEDS_LOGIN
    sessions: int = 0    # CONFIRM_SESSIONS: how many are working


def switches_of(status: Status) -> Switches:
    return Switches(follows=status.sync_follows, one_click=status.one_click_desktop)


def switches_to_show(status: Status | None, current: Switches, changed_at: float | None) -> Switches:
    """The switches as the window shows them: the status's, unless the user changed one at ``changed_at`` and no status
    written after the change has been read yet, when the change stands."""
    if status is None:
        return current
    if changed_at is not None and (status.generated_at is None or status.generated_at < changed_at):
        return current
    return switches_of(status)


def switch_buttons(status: Status, account: Account, switches: Switches) -> tuple[SwitchButton, ...]:
    """The buttons on ``account``'s card, in the order they stand; at most the first is the accent, and only on the
    recommended account's card."""
    offered = []
    if switches.one_click and not account.is_desktop:
        offered.append((APP, "Switch here" if switches.follows else "Switch app here"))
    if not switches.follows and not account.is_cli:
        offered.append((CLI, "Switch CLI here"))
    recommended = status.recommended_account == account.uuid
    return tuple(SwitchButton(client, text, recommended and index == 0) for index, (client, text) in enumerate(offered))


def switch_entries(status: Status, client: str, switches: Switches) -> tuple[SwitchEntry, ...]:
    """The accounts a menu offers to switch ``client`` to, in status.json's order: every listed account but the one
    the client uses, none while the client cannot be switched alone (the app with one-click off, the CLI while it
    follows the app). An account the user hid is offered once *Arrange accounts…* shows it again. The recommended
    account says so where it stands, every menu keeping the one order of the accounts."""
    if client == APP and not switches.one_click:
        return ()
    if client == CLI and switches.follows:
        return ()
    uses = (lambda a: a.is_desktop) if client == APP else (lambda a: a.is_cli)
    return tuple(SwitchEntry(client, a.uuid, a.label + ("  (use next)" if a.uuid == status.recommended_account else ""))
                 for a in status.listed if not uses(a))


def mode_words(switches: Switches) -> str:
    """The header's word on how the two switch."""
    return "the CLI follows the app" if switches.follows else "the CLI and the app switch apart"


def plan_app_switch(account: Account, sessions: int) -> Plan:
    """What asking to switch the desktop app to ``account`` leads to, ``sessions`` Code sessions being at work."""
    if not account.desktop_archived:
        return Plan(NEEDS_LOGIN)
    return plan_close(sessions)


def plan_close(sessions: int) -> Plan:
    """What asking for anything that closes the desktop app leads to."""
    return Plan(CONFIRM_SESSIONS, sessions) if sessions > 0 else Plan(RUN)
