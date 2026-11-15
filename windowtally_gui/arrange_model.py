"""The *Arrange accounts…* window's logic: the accounts in the user's order, moved one place at a time or put back in
the default order, by name, a name of the user's own for each, held to WindowTally's rules, and whether each is shown.
No toolkit.

The window lists every account status.json lists, those it marks hidden included, in the user's order
(``windowtally.accounts.arranged`` over the settings' ``accountOrder``). Unlike every other surface it does not put the
accounts in use first: what it arranges is the order the others follow after them. The names, and which accounts are
hidden, come from the settings, not from status.json, whose labels may be a pass old; an account the user has not
named is shown by its e-mail's local part. An account hidden is left out of every other list of WindowTally while
neither client uses it, and is never recommended (``windowtally.settings``, ``hiddenAccounts``); here it is shown
again.

A name is held to WindowTally's rules (``windowtally.settings.name_problem``) and, here, also differs from every other
account's shown name, case aside, which the settings file cannot check: it knows no e-mail. The spaces around a name
typed are dropped. A cleared name, or one typed as the account's default, is no name: the account is shown by its
default.

The names the settings hold for accounts status.json does not list — an account that appeared since the service's last
pass, or a UUID written by hand that no account here has — are kept: the window cannot show them, so it writes them
back as it read them. Such a name still blocks an equal one, case aside, as the settings file would refuse it; the
window says so where the name is typed, naming the account by its UUID, the one thing it knows of it, since nothing in
the window can clear that name. Such accounts the settings hide are kept hidden the same way.

What OK writes is the order, the names and the hidden accounts together, through
``windowtally.settings.edit_account_arrangement``, and only where any changed. The order is written as none while it is
the order by name, so that an account added later takes its place by name rather than at the end.

The settings can change while the window stands open — by hand: no other part of WindowTally writes the three keys, and
only one window runs. So OK does not write back what the window read: it lays what the window changed onto the settings
as they stand then (``onto``), read under the file's edit lock. The order counts as one thing, since two orders cannot
be interleaved with any meaning, each listed account's name as one more and whether it is hidden as one more, and the
names and the hiding of the accounts the window does not list are never the window's. Two orders are one where they
show the listed accounts alike, however they are written. Whether an account is hidden has two values, so the settings
can only have left it as read or changed it as the window did: the window's own change of it is written as the
window's. What the window left alone is written as the settings hold it then, an order set elsewhere less the UUIDs no
listed account has, which are dropped at every save of the arrangement. Where the window and the settings both changed one
thing, each differently, nothing is written and the window says what the settings changed (``Conflict``); once told
(``acknowledge``), OK again writes the window's value over what it was told of, unless the settings changed it once
more. A name the window gives that the settings, as they stand, have meanwhile given another account, or made another
account's shown name, is refused, nothing written, for another name to be chosen; a name cleared is never refused,
as where it is typed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from windowtally.accounts import arranged, default_label
from windowtally.settings import Settings, name_problem

from .status_model import Status


@dataclass(frozen=True)
class Row:
    uuid: str
    email: str | None
    default: str            # the name the account's e-mail gives it
    name: str | None        # the user's own
    hidden: bool = False    # the user hid it

    @property
    def shown(self) -> str:
        return self.name or self.default


class Conflict(ValueError):
    """The settings changed, since the window read them, something the window changed too, each differently; the
    message says what, and ``order`` (None where the order is not among them) and ``names`` are what the settings hold
    of those things now, for ``Arrangement.acknowledge``. Whether an account is hidden is never among them: having two
    values, it cannot be changed both here and elsewhere, each differently."""

    def __init__(self, message: str, order: tuple[str, ...] | None, names: Mapping[str, str | None]):
        super().__init__(message)
        self.order = order
        self.names = dict(names)


class Arrangement:
    """The accounts as the window arranges them; ``rows`` in the order shown, ``kept`` the names of accounts it does
    not list, by UUID, and ``kept_hidden`` the accounts it does not list that the settings hide."""

    def __init__(self, rows: list[Row], names: Mapping[str, str] | None = None, order: Sequence[str] = (),
                 hidden: Sequence[str] = ()):
        """``names``, ``order`` and ``hidden`` are the settings' as read; the names, and whether hidden, of accounts
        ``rows`` lists are the rows' own, the rest kept."""
        self.rows = list(rows)
        listed = {r.uuid for r in self.rows}
        self.kept = {uuid: name for uuid, name in (names or {}).items() if uuid not in listed}
        self.kept_hidden = tuple(uuid for uuid in hidden if uuid not in listed)
        self._saved = (self.order(), self.names(), self.hidden())
        self._opened = {r.uuid: r.name for r in self.rows}          # the listed accounts' names as the window opened
        self._opened_hidden = {r.uuid: r.hidden for r in self.rows}  # and whether each was hidden
        self._opened_order = tuple(order)                           # the settings' order as the window opened
        # The settings as last read or told of, against which a change made elsewhere is told apart.
        self._read_order = tuple(order)
        self._read_names = dict(names or {})

    @classmethod
    def of(cls, status: Status, settings: Settings) -> Arrangement:
        names = settings.names
        hidden = settings.hidden
        rows = [Row(a.uuid, a.email, default_label(a.uuid, a.email), names.get(a.uuid), a.uuid in hidden)
                for a in status.accounts]
        return cls(arranged(rows, settings.account_order, lambda r: r.uuid, lambda r: r.shown), names,
                   settings.account_order, settings.hidden_accounts)

    def row(self, uuid: str) -> Row:
        return self.rows[self.index(uuid)]

    def index(self, uuid: str) -> int:
        return next(i for i, r in enumerate(self.rows) if r.uuid == uuid)

    def can_move(self, uuid: str, step: int) -> bool:
        """Whether the account can move ``step`` places: -1 up, 1 down."""
        return 0 <= self.index(uuid) + step < len(self.rows)

    def move(self, uuid: str, step: int) -> bool:
        """Moves the account ``step`` places, -1 up or 1 down; False, and nothing moved, at the end of the list."""
        if not self.can_move(uuid, step):
            return False
        i = self.index(uuid)
        self.rows[i], self.rows[i + step] = self.rows[i + step], self.rows[i]
        return True

    def _by_name(self) -> list[Row]:
        # The service's own order by name, ties included: any other tie-break would let an order the user set between
        # two accounts shown by one name count as the order by name, and be written as none.
        return arranged(self.rows, (), lambda r: r.uuid, lambda r: r.shown)

    def by_name(self) -> None:
        """Puts the accounts back in the default order, by their shown names."""
        self.rows = self._by_name()

    def is_by_name(self) -> bool:
        return [r.uuid for r in self.rows] == [r.uuid for r in self._by_name()]

    def name_problem(self, uuid: str, text: str) -> str | None:
        """Why ``text`` cannot be the account's name, in words; None when it can, or when it clears the name."""
        name = text.strip()
        row = self.row(uuid)
        if not name or name == row.default:
            return None
        problem = name_problem(name)
        if problem:
            return f"Not usable: {problem}."
        clash = next((r for r in self.rows if r.uuid != uuid and r.shown.casefold() == name.casefold()), None)
        if clash is not None:
            whose = f" ({clash.email})" if clash.email else ""
            return f"Not usable: another account{whose} is shown as {clash.shown}."
        held = next((u for u, kept in self.kept.items() if kept.casefold() == name.casefold()), None)
        if held is not None:
            return f"Not usable: settings.json keeps it for an unlisted account ({held}); remove it there to free it."
        return None

    def rename(self, uuid: str, text: str) -> str | None:
        """Names the account ``text``, or clears its name where ``text`` is empty or its default; the problem, and the
        name left as it was, where ``text`` cannot be its name."""
        problem = self.name_problem(uuid, text)
        if problem:
            return problem
        name = text.strip()
        i = self.index(uuid)
        self.rows[i] = replace(self.rows[i], name=name if name and name != self.rows[i].default else None)
        return None

    def set_shown(self, uuid: str, shown: bool) -> None:
        """Shows the account in WindowTally's lists, or hides it from them."""
        i = self.index(uuid)
        self.rows[i] = replace(self.rows[i], hidden=not shown)

    def order(self) -> tuple[str, ...]:
        """The order to write: none while it is the order by name."""
        return () if self.is_by_name() else tuple(r.uuid for r in self.rows)

    def names(self) -> dict[str, str]:
        """The names to write, by UUID: the listed accounts' in the order shown, then those kept for accounts the
        window does not list."""
        return {r.uuid: r.name for r in self.rows if r.name} | self.kept

    def hidden(self) -> tuple[str, ...]:
        """The accounts to write as hidden: the listed ones hidden, in the order shown, then those kept for accounts
        the window does not list."""
        return tuple(r.uuid for r in self.rows if r.hidden) + self.kept_hidden

    def changed(self) -> bool:
        return (self.order(), self.names(), self.hidden()) != self._saved

    def _shows(self, order: Sequence[str]) -> tuple[str, ...]:
        """The listed accounts as ``order`` puts them, by the names the window shows: two orders that put them alike
        are one, however they are written."""
        return tuple(r.uuid for r in arranged(self.rows, order, lambda r: r.uuid, lambda r: r.shown))

    def onto(self, current: Settings) -> tuple[tuple[str, ...], dict[str, str], tuple[str, ...]]:
        """The order, names and hidden accounts to write over ``current``, the settings as they stand at OK: what the
        window changed since it opened, laid onto what they hold. Changes nothing of the window's. Conflict, nothing to
        write, where the settings changed something the window changed too, each differently, since it was read or
        last told of; ValueError, in words, where a name the window gives clashes with the settings as they stand."""
        theirs = current.names
        listed = {r.uuid for r in self.rows}
        told: list[str] = []
        told_order: tuple[str, ...] | None = None
        told_names: dict[str, str | None] = {}
        order = self.order()
        shown = self._shows(current.account_order)
        if order == self._saved[0]:
            if shown != self._shows(self._opened_order):
                order = tuple(uuid for uuid in current.account_order if uuid in listed)
        elif shown not in (self._shows(self._read_order), self._shows(order)):
            told.append("the order of the accounts")
            told_order = current.account_order
        names: dict[str, str] = {}
        given: list[Row] = []       # the rows whose name is the window's
        for row in self.rows:
            mine, other = row.name, theirs.get(row.uuid)
            if mine == self._opened[row.uuid]:
                name = other
            else:
                name = mine
                given.append(row)
                if other not in (self._read_names.get(row.uuid), mine):
                    told.append(f"the name of {row.email or row.uuid}, now {repr(other) if other else 'none'}")
                    told_names[row.uuid] = other
            if name:
                names[row.uuid] = name
        kept = {uuid: name for uuid, name in theirs.items() if uuid not in listed}
        # An account's hiding the window changed is the window's: the settings can only have left it as it was read or
        # changed it as the window did. One the window left alone is the settings' as they stand.
        hidden = [row.uuid for row in self.rows
                  if (row.hidden if row.hidden != self._opened_hidden[row.uuid] else row.uuid in current.hidden)]
        hidden += [uuid for uuid in current.hidden_accounts if uuid not in listed]
        if told:
            raise Conflict(f"settings.json changed meanwhile: {'; '.join(told)}. OK again overwrites it; Cancel keeps it.",
                           told_order, told_names)
        for row in given:
            if row.name is None:
                continue
            folded = row.name.casefold()
            clash = next((r for r in self.rows if r.uuid != row.uuid
                          and (names.get(r.uuid) or r.default).casefold() == folded), None)
            if clash is not None:
                raise ValueError(f"settings.json now shows another account ({clash.email or clash.uuid}) as "
                                 f"{names.get(clash.uuid) or clash.default}; rename {row.email or row.uuid}.")
            held = next((uuid for uuid, name in kept.items() if name.casefold() == folded), None)
            if held is not None:
                raise ValueError(f"settings.json now keeps {kept[held]} for an unlisted account ({held}); rename "
                                 f"{row.email or row.uuid}.")
        return tuple(order), names | kept, tuple(hidden)

    def acknowledge(self, conflict: Conflict) -> None:
        """Counts what ``conflict`` said the settings hold as told: the next ``onto`` lays the window's value over it,
        unless the settings change it once more."""
        if conflict.order is not None:
            self._read_order = conflict.order
        self._read_names.update(conflict.names)
