"""Accounts whose plan has ended set aside, and the window's shorter words: the service lists such accounts after the
others; the window gives one no client uses a line under the cards, saying when its plan ended and when its week
resets, and the tooltip leaves it out; a weekly reset reads by its weekday and time; a card says its reading's age
once where both windows rest on one reading; and the header, the plan line and the tooltip say what they say once."""

import json
import unittest
from datetime import date
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, epoch, status_account, status_document,
                      status_subscription, status_window)
from windowtally.accounts import Account
from windowtally.limits import AccountStanding, Recommendation, WeeklyAnchor, WindowStanding
from windowtally.status_file import shown_order
from windowtally.status_file import status_document as written_document
from windowtally_gui import formatting
from windowtally_gui.live_model import TOOLTIP_LIMIT, live_view, tray_view
from windowtally_gui.status_model import snapshot_of

T0 = epoch("2026-10-20T10:00:00Z")   # a Tuesday
ACCOUNT_C = "cccccccc-0000-4000-8000-000000000003"
ACCOUNT_D = "dddddddd-0000-4000-8000-000000000004"
EMAIL_C = "gamma@example.com"
EMAIL_D = "delta@example.com"
WEEK_RESET = T0 + 5 * 86400 + 3600
BEFORE_LAST_RESPONSE = T0 - 900   # a reading the last response of an account as of T0, 10 minutes before it, came after

ENDED = status_subscription(state="ended", plan=None, planName=None, paidUntil="2026-10-01", daysLeft=None,
                            profileCheck="no-bill-today")


def snapshot(doc: dict):
    return snapshot_of(Path("status.json"), json.dumps(doc))


def ended_account(uuid=ACCOUNT_B, email=EMAIL_B, **changes) -> dict:
    """An account no client uses whose plan ended on Thu 1 Oct, its week rolled forward to nothing."""
    data = status_account(uuid, email, at=T0, desktop=False, cli=False, plan=ENDED,
                          weekly=status_window("current", 0.0, WEEK_RESET, as_of=T0 - 40 * 86400, anchor_exact=True))
    data.update(changes)
    return data


def standing(uuid: str, email: str, desktop: bool = False) -> AccountStanding:
    return AccountStanding(Account(uuid=uuid, email=email),
                           WindowStanding("five_hour", "not_started", None, None, None, False, None),
                           WindowStanding("seven_day", "unknown", None, None, None, False, None),
                           WeeklyAnchor(T0 + 86400, exact=False), None, desktop, False)


def subscription(state: str) -> SimpleNamespace:
    """A subscription as the billing report gives it, in the fields status.json writes."""
    return SimpleNamespace(state=state, plan=None, paid_until=date(2026, 10, 1), days_left=None, renew_soon=False,
                           this_month=Fraction(0), profile_plan=None, profile_check="no-profile")


class OrderTest(unittest.TestCase):
    def test_an_ended_plan_stands_after_the_others_each_group_in_the_users_order(self):
        standings = [standing(ACCOUNT_A, EMAIL_A), standing(ACCOUNT_B, EMAIL_B), standing(ACCOUNT_C, EMAIL_C),
                     standing(ACCOUNT_D, EMAIL_D)]
        order = [s.account.uuid for s in shown_order(standings, [ACCOUNT_A, ACCOUNT_C, ACCOUNT_B, ACCOUNT_D],
                                                     {ACCOUNT_A, ACCOUNT_C})]
        self.assertEqual(order, [ACCOUNT_B, ACCOUNT_D, ACCOUNT_A, ACCOUNT_C])

    def test_an_account_in_use_stands_first_whatever_its_plan(self):
        standings = [standing(ACCOUNT_A, EMAIL_A, desktop=True), standing(ACCOUNT_B, EMAIL_B)]
        self.assertEqual([s.account.uuid for s in shown_order(standings, (), {ACCOUNT_A})], [ACCOUNT_A, ACCOUNT_B])

    def test_status_json_lists_an_ended_plan_last_by_its_bills(self):
        plans = {ACCOUNT_A: subscription("ended"), ACCOUNT_B: subscription("active"), ACCOUNT_C: subscription("none")}
        billing = SimpleNamespace(configured=True, for_account=plans.get, reminder_days=None, this_month=Fraction(0))
        doc = written_document([standing(ACCOUNT_A, EMAIL_A), standing(ACCOUNT_B, EMAIL_B),
                                standing(ACCOUNT_C, EMAIL_C)], Recommendation(None, "", None), now=T0,
                               desktop_account=None, cli_account=None, cli_condition=None, billing=billing)
        self.assertEqual([(a["uuid"], a["subscription"]["state"]) for a in doc["accounts"]],
                         [(ACCOUNT_B, "active"), (ACCOUNT_C, "none"), (ACCOUNT_A, "ended")])


class EndedLineTest(unittest.TestCase):
    def test_an_ended_plan_no_client_uses_has_a_line_not_a_card(self):
        view = live_view(snapshot(status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0), ended_account()],
                                                  at=T0, oneClickDesktop=True)), T0)
        self.assertEqual([c.uuid for c in view.cards], [ACCOUNT_A])
        [row] = view.ended
        self.assertEqual((row.uuid, row.label, row.email), (ACCOUNT_B, "beta", ""))
        self.assertEqual(row.text, f"plan ended Thu 1 Oct · week resets {formatting.when(WEEK_RESET)}")
        self.assertEqual([b.text for b in row.switches], ["Switch here"])

    def test_one_a_client_uses_keeps_its_card(self):
        view = live_view(snapshot(status_document([ended_account(ACCOUNT_A, EMAIL_A, isDesktop=True, isCli=True)],
                                                  at=T0)), T0)
        self.assertEqual(([c.uuid for c in view.cards], view.ended), ([ACCOUNT_A], ()))
        self.assertEqual(view.cards[0].plan.text, "ended Thu 1 Oct")

    def test_a_name_of_the_users_own_brings_the_e_mail(self):
        view = live_view(snapshot(status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0),
                                                   ended_account(label="Studio")], at=T0)), T0)
        self.assertEqual(view.ended[0].email, EMAIL_B)


class CardWordsTest(unittest.TestCase):
    def card(self, **changes):
        return live_view(snapshot(status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0, **changes)], at=T0)),
                         T0).cards[0]

    def test_a_weekly_reset_reads_by_weekday_and_time(self):
        weekly = self.card(weekly=status_window("current", 69.0, WEEK_RESET, as_of=T0 - 60, anchor_exact=True)).weekly
        self.assertEqual(weekly.detail, f"resets {formatting.when(WEEK_RESET)} (in 5d 1h)")
        self.assertNotIn("Oct", weekly.detail)

    def test_a_weekly_reset_more_than_six_days_off_carries_its_date(self):
        far = T0 + 6 * 86400 + 18 * 3600
        weekly = self.card(weekly=status_window("current", 1.0, far, as_of=T0 - 60, anchor_exact=True)).weekly
        self.assertEqual(weekly.detail, f"resets {formatting.when(far, True)} (in 6d 18h)")

    def test_one_reading_is_said_once_after_the_last_response(self):
        card = self.card()
        self.assertEqual(card.heading, "last response 10m ago", "read a minute ago, since the last response: no age")
        self.assertNotIn("read", card.five_hour.note + card.weekly.note)
        card = self.card(five_hour=status_window(resets=T0 + 80 * 60, as_of=BEFORE_LAST_RESPONSE),
                         weekly=status_window("current", 69.0, WEEK_RESET, as_of=BEFORE_LAST_RESPONSE,
                                              anchor_exact=True))
        self.assertEqual(card.heading, "last response 10m ago · read 15m ago")
        self.assertNotIn("read", card.five_hour.note + card.weekly.note)

    def test_readings_that_differ_are_said_beside_each_window(self):
        weekly = status_window("current", 69.0, WEEK_RESET, as_of=T0 - 7200, anchor_exact=True)
        card = self.card(weekly=weekly)
        self.assertEqual(card.heading, "last response 10m ago")
        self.assertEqual((card.five_hour.note, card.weekly.note), ("", "read 2h 00m ago"),
                         "the 5-hour reading, taken since the last response, says no age")
        card = self.card(five_hour=status_window(resets=T0 + 80 * 60, as_of=BEFORE_LAST_RESPONSE), weekly=weekly)
        self.assertEqual(card.heading, "last response 10m ago")
        self.assertEqual((card.five_hour.note, card.weekly.note), ("read 15m ago", "read 2h 00m ago"))

    def test_a_5_hour_window_with_no_limit_is_its_name_alone(self):
        card = self.card(five_hour=status_window("no_limit", None, None, as_of=T0 - 300))
        self.assertEqual((card.five_hour.figure, card.five_hour.detail, card.five_hour.note, card.five_hour.metered),
                         ("no limit", "", "", False))
        self.assertEqual(card.heading, "last response 10m ago", "the weekly reading is a minute old: no age")
        card = self.card(five_hour=status_window("no_limit", None, None, as_of=T0 - 300),
                         weekly=status_window("current", 69.0, WEEK_RESET, as_of=BEFORE_LAST_RESPONSE,
                                              anchor_exact=True))
        self.assertTrue(card.heading.endswith("read 15m ago"), "the weekly reading's age, said once")
        self.assertEqual((card.five_hour.note, card.weekly.note), ("", ""))

    def test_the_week_by_product_is_said_only_where_more_than_one_product_has_a_share(self):
        def products(rows):
            weekly = status_window("current", 69.0, WEEK_RESET, as_of=T0 - 60, anchor_exact=True)
            weekly["byProduct"] = {"asOf": status_window(as_of=T0 - 3600)["asOf"], "rows": rows}
            return self.card(weekly=weekly).weekly.products
        code = {"key": "claude_code", "name": "Claude Code", "percent": 100}
        self.assertEqual(products([code, {"key": "chat", "name": "Chats", "percent": 0}]), "")
        self.assertEqual(products([dict(code, percent=89), {"key": "chat", "name": "Chats", "percent": 11}]),
                         "by product 1h 00m ago: Claude Code 89%, Chats 11%")

    def test_the_plan_line_says_no_monthly_cost(self):
        plan = self.card(plan=status_subscription()).plan
        self.assertEqual((plan.text, plan.note), ("Ultra · paid until Sat 7 Nov", ""))
        near = self.card(plan=status_subscription(daysLeft=3)).plan
        self.assertEqual((near.text, near.note), ("Ultra · paid until Sat 7 Nov (3 days left)", ""))


class HeaderTest(unittest.TestCase):
    def test_one_line_for_the_status_and_one_account_in_both_clients(self):
        header = live_view(snapshot(status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0)], at=T0 - 120)),
                           T0).header
        self.assertEqual(header.status_line, "Updated 2m ago")
        self.assertEqual(header.in_use_line, "the CLI follows the app", "alpha's card names both clients on its chips")
        unlisted = status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0, desktop=False, cli=False)], at=T0 - 120,
                                   desktopAccount=ACCOUNT_C, cliAccount=ACCOUNT_C)
        header = live_view(snapshot(unlisted), T0).header
        self.assertTrue(header.in_use_line.startswith("Desktop app and CLI: cccccccc · "),
                        f"an account in use that no card names, said once for both clients: {header.in_use_line}")

    def test_the_time_left_is_added_to_the_moment_the_reason_names_once(self):
        doc = status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0)], at=T0,
                              recommended={"account": None, "reliefAt": status_window(as_of=T0 + 3 * 3600)["asOf"],
                                           "reason": "Every account is at its limit. The first opens Tue 13:00.",
                                           "reliefExact": True})
        self.assertEqual(live_view(snapshot(doc), T0).header.next_line,
                         "Next: Every account is at its limit. The first opens Tue 13:00 (in 3h 00m).")
        doc["recommended"].update(reliefExact=False, reason="Every account is at its limit. The first opens ≈Tue 13:00.")
        self.assertEqual(live_view(snapshot(doc), T0).header.next_line,
                         "Next: Every account is at its limit. The first opens ≈Tue 13:00 (in ≈3h 00m).")


class TooltipTest(unittest.TestCase):
    def test_the_accounts_in_use_then_the_recommendation_then_the_others_an_ended_plan_left_out(self):
        doc = status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0),
                               status_account(ACCOUNT_C, EMAIL_C, at=T0, desktop=False, cli=False),
                               ended_account()], at=T0)
        lines = tray_view(snapshot(doc), T0).tooltip.split("\n")
        self.assertEqual([line.split("  ")[0] for line in lines], ["alpha (app, CLI)", "Next: alpha", "gamma"])
        self.assertTrue(lines[0].endswith(f"week 69% ↻{formatting.when(T0 + 3 * 86400)}"), lines[0])

    def test_a_tooltip_too_long_loses_whole_lines_from_its_end(self):
        accounts = [status_account(ACCOUNT_A, "a-long-account-name@example.com", at=T0)] + [
            status_account(uuid, f"another-long-name-{n}@example.com", at=T0, desktop=False, cli=False)
            for n, uuid in enumerate((ACCOUNT_B, ACCOUNT_C, ACCOUNT_D))]
        tooltip = tray_view(snapshot(status_document(accounts, at=T0)), T0).tooltip
        self.assertLessEqual(len(tooltip), TOOLTIP_LIMIT)
        lines = tooltip.split("\n")
        self.assertEqual((lines[1], lines[-1]), ("Next: a-long-account-name", "…"))
        self.assertTrue(lines[0].startswith("a-long-account-name (app, CLI)  5h"), lines[0])
        for line in lines[2:-1]:
            self.assertRegex(line, r"^another-long-name-\d  5h .* · week .*↻\w{3} \d\d:\d\d$", "whole lines only")

    def test_the_recommendation_is_kept_though_the_lines_before_it_run_over(self):
        reason = "No account is left to recommend: every account is hidden or its plan has ended."
        doc = status_document([status_account(ACCOUNT_A, "a-long-account-name@example.com", at=T0),
                               status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False)], at=T0,
                              recommended={"account": None, "reason": reason, "reliefAt": None, "reliefExact": False})
        tooltip = tray_view(snapshot(doc), T0).tooltip
        self.assertEqual(len(tooltip), TOOLTIP_LIMIT)
        self.assertTrue(tooltip.split("\n")[1].startswith("No account is left to recommend"), tooltip)
        self.assertNotIn("beta", tooltip)


if __name__ == "__main__":
    unittest.main()
