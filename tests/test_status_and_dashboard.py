"""status_file and dashboard: the plugin's contract and the history page."""

import json
import re
import unittest

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bridge_line, epoch,
                      scripts_on)
from windowtally import palette, rings
from windowtally.accounts import Account, by_org, load_registry
from windowtally.attribution import attribute
from windowtally.dashboard import account_slots, account_views, render_dashboard
from windowtally.ingest_app_history import ingest_app_history
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger
from windowtally.limits import AccountStanding, Recommendation, WeeklyAnchor, WindowStanding, recommend, standings
from windowtally.status_file import STATUS_VERSION, status_document, write_status

T0 = epoch("2026-10-20T10:00:00Z")


class StatusFileTest(unittest.TestCase):
    def test_document_follows_the_contract(self):
        account = Account(uuid=ACCOUNT_A, email=EMAIL_A)
        s = AccountStanding(account,
                            WindowStanding("five_hour", "running", 26.04, T0 + 3600, T0 - 60, False, None),
                            WindowStanding("seven_day", "current", 60.0, T0 + 86400, T0 - 60, True, T0 + 7200),
                            WeeklyAnchor(T0 + 86400, exact=False), T0 - 30, True, False)
        doc = status_document([s], Recommendation(ACCOUNT_A, "alpha has room left.", None), now=T0,
                              desktop_account=ACCOUNT_A, cli_account=None, cli_condition=None,
                              source_errors=["transcripts: denied"])
        self.assertEqual(doc["v"], STATUS_VERSION)
        self.assertEqual(doc["generatedAt"], "2026-10-20T10:00:00.000Z")
        self.assertEqual(doc["sourceErrors"], ["transcripts: denied"])
        self.assertEqual(doc["recommended"], {"account": ACCOUNT_A, "reason": "alpha has room left.", "reliefAt": None,
                                              "reliefExact": False})
        entry = doc["accounts"][0]
        self.assertEqual((entry["uuid"], entry["label"], entry["isDesktop"], entry["isCli"]), (ACCOUNT_A, "alpha", True, False))
        self.assertEqual(entry["fiveHour"], {"state": "running", "percent": 26.0, "resetsAt": "2026-10-20T11:00:00.000Z",
                                             "asOf": "2026-10-20T09:59:00.000Z", "estimated": False, "exhaustsAt": None,
                                             "anchorExact": False})
        self.assertEqual(entry["weekly"]["anchorExact"], False)
        self.assertEqual(entry["weekly"]["exhaustsAt"], "2026-10-20T12:00:00.000Z")

    def test_optional_switching_fields(self):
        account = Account(uuid=ACCOUNT_A, email=EMAIL_A)
        s = AccountStanding(account,
                            WindowStanding("five_hour", "running", 26.0, T0 + 3600, T0 - 60, False, None),
                            WindowStanding("seven_day", "current", 60.0, T0 + 86400, T0 - 60, True, None),
                            WeeklyAnchor(T0 + 86400, exact=False), T0 - 30, True, False)
        doc = status_document([s], Recommendation(ACCOUNT_A, "ok", None), now=T0,
                              desktop_account=ACCOUNT_A, cli_account=None, cli_condition=None,
                              sync_follows=False, one_click_desktop=True, working_sessions=3,
                              desktop_archived={ACCOUNT_A})
        self.assertEqual(doc["syncFollows"], False)
        self.assertEqual(doc["oneClickDesktop"], True)
        self.assertEqual(doc["workingSessions"], 3)
        self.assertTrue(doc["accounts"][0]["desktopArchived"])

    def test_a_desktop_app_at_its_sign_in_page_is_said_and_marks_no_account(self):
        account = Account(uuid=ACCOUNT_A, email=EMAIL_A)
        s = AccountStanding(account,
                            WindowStanding("five_hour", "running", 26.0, T0 + 3600, T0 - 60, False, None),
                            WindowStanding("seven_day", "current", 60.0, T0 + 86400, T0 - 60, True, None),
                            WeeklyAnchor(T0 + 86400, exact=False), T0 - 30, False, True)
        doc = status_document([s], Recommendation(ACCOUNT_A, "ok", None), now=T0, desktop_account=None,
                              desktop_signed_out=True, cli_account=ACCOUNT_A, cli_condition=None)
        self.assertEqual((doc["desktopAccount"], doc["desktopSignedIn"], doc["cliAccount"]), (None, False, ACCOUNT_A))
        self.assertEqual((doc["accounts"][0]["isDesktop"], doc["accounts"][0]["isCli"]), (False, True))
        signed_in = status_document([s], Recommendation(ACCOUNT_A, "ok", None), now=T0, desktop_account=None,
                                    cli_account=ACCOUNT_A, cli_condition=None)
        self.assertNotIn("desktopSignedIn", signed_in, "written only while the app is at its sign-in page")

    def test_a_desktop_app_that_is_not_running_is_said_and_keeps_its_account(self):
        account = Account(uuid=ACCOUNT_A, email=EMAIL_A)
        s = AccountStanding(account,
                            WindowStanding("five_hour", "running", 26.0, T0 + 3600, T0 - 60, False, None),
                            WindowStanding("seven_day", "current", 60.0, T0 + 86400, T0 - 60, True, None),
                            WeeklyAnchor(T0 + 86400, exact=False), T0 - 30, True, True)
        doc = status_document([s], Recommendation(ACCOUNT_A, "ok", None), now=T0, desktop_account=ACCOUNT_A,
                              desktop_not_running=True, cli_account=ACCOUNT_A, cli_condition=None)
        self.assertEqual((doc["desktopAccount"], doc["desktopRunning"]), (ACCOUNT_A, False))
        self.assertTrue(doc["accounts"][0]["isDesktop"], "the account it starts on")
        running = status_document([s], Recommendation(ACCOUNT_A, "ok", None), now=T0, desktop_account=ACCOUNT_A,
                                  cli_account=ACCOUNT_A, cli_condition=None)
        self.assertNotIn("desktopRunning", running, "written only while the app is not running")

    def test_optional_fields_absent_at_defaults(self):
        account = Account(uuid=ACCOUNT_A, email=EMAIL_A)
        s = AccountStanding(account,
                            WindowStanding("five_hour", "running", 26.0, T0 + 3600, T0 - 60, False, None),
                            WindowStanding("seven_day", "current", 60.0, T0 + 86400, T0 - 60, True, None),
                            WeeklyAnchor(T0 + 86400, exact=False), T0 - 30, True, False)
        doc = status_document([s], Recommendation(ACCOUNT_A, "ok", None), now=T0,
                              desktop_account=ACCOUNT_A, cli_account=None, cli_condition=None)
        self.assertNotIn("syncFollows", doc)
        self.assertNotIn("oneClickDesktop", doc)
        self.assertNotIn("workingSessions", doc)
        self.assertNotIn("desktopArchived", doc["accounts"][0])

    def test_written_whole(self):
        machine = Machine()
        try:
            path = machine.paths.status_file
            write_status(path, {"v": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"v": 1})
            self.assertEqual([p.name for p in path.parent.iterdir()], ["status.json"])
        finally:
            machine.close()


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        self.machine.app_history([(T0 - 7200, ORG_B, 10, 30), (T0 - 3600, ORG_A, 20, 50), (T0 - 1800, ORG_A, 25, 52)])
        self.machine.transcript("s1", [bridge_line("s1", ACCOUNT_A, ORG_A)] + assistant_lines("m1", T0 - 2000, "s1"))
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.registry, _ = load_registry(self.machine.paths.accounts_dir)
        ingest_app_history(self.ledger, self.machine.paths.plan_usage_history, by_org(self.registry))
        ingest_transcripts(self.ledger, self.machine.paths.projects_dir)
        attribute(self.ledger)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def render(self):
        current = standings(self.ledger, self.registry.values(), T0)
        return render_dashboard(self.ledger, self.registry, current, recommend(current), T0)

    def test_a_table_shows_as_many_rows_as_the_window_s_and_scrolls_under_headings_and_totals_that_stay(self):
        from windowtally import history
        from windowtally_gui import table_view
        self.assertIs(table_view.TABLE_ROWS, history.TABLE_ROWS)     # one number for the page and the window
        html = self.render()
        wraps = " ".join(re.findall(r"\.windowtally \.table-wrap \{([^}]*)\}", html))
        self.assertIn("overflow:auto", wraps)
        self.assertIn(f"max-height:calc({history.TABLE_ROWS + 1} * (13px * 1.45 + 11px) + 17px)", wraps)
        self.assertIn("font-size:13px", re.search(r"\.windowtally table \{([^}]*)\}", html).group(1))
        self.assertIn("padding:5px 8px", re.search(r"\.windowtally th, \.windowtally td \{([^}]*)\}", html).group(1))
        heading = re.search(r"\.windowtally \.table-wrap thead th \{([^}]*)\}", html).group(1)
        self.assertIn("position:sticky", heading)
        self.assertIn("top:0", heading)
        total = re.search(r"\.windowtally \.table-wrap tr\.total td \{([^}]*)\}", html).group(1)
        self.assertIn("position:sticky", total)
        self.assertIn("bottom:0", total)
        self.assertIn('<tr class="total"><td class="l"><b>', html)       # the tokens tables' total row
        self.assertIn('class="panel table-wrap"><table><thead>', html)

    def test_self_contained(self):
        html = self.render()
        # The page's own script, inline, and no other: none loaded from elsewhere, none in an attribute or a link.
        self.assertEqual(scripts_on(html), ["<script>"])
        self.assertIsNone(re.search(r'(?:src|href)\s*=\s*"(?:https?:)?//', html), "no external resource")
        self.assertIn("alpha", html)
        self.assertIn("beta", html)

    def test_the_one_script_keeps_a_wheel_gesture_to_the_page_or_the_table_it_began_on(self):
        from windowtally import history
        html = self.render()
        scripts = re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S)
        self.assertEqual(len(scripts), 1)
        attributes, script = scripts[0]
        self.assertEqual(attributes, "", "inline, never loaded from elsewhere")
        self.assertIn(f"PAUSE = {round(history.WHEEL_PAUSE * 1000)}", script)   # one number for the page and the window
        self.assertIn('addEventListener("wheel"', script)
        self.assertIn("{passive: false}", script)           # a passive listener could not keep a table from the turn
        self.assertIn('closest(".table-wrap")', script)
        self.assertIn('class="panel table-wrap"', html)

    def test_weeks_begin_on_mondays(self):
        from datetime import date
        weeks = re.findall(r"week of (\d{4}-\d\d-\d\d)", self.render())
        self.assertTrue(weeks)
        self.assertEqual({date.fromisoformat(w).weekday() for w in weeks}, {0})

    def test_accounts_keep_their_colour_in_first_seen_order(self):
        views = account_views(self.ledger, self.registry)
        self.assertEqual([(v.label, v.color) for v in views],
                         [("beta", "var(--series-1)"), ("alpha", "var(--series-2)")])
        self.assertEqual([(a.label, token) for a, token in account_slots(self.ledger, self.registry)],
                         [("beta", "series-1"), ("alpha", "series-2")])

    def test_a_ring_takes_its_window_s_warning_colours(self):
        account = Account(uuid=ACCOUNT_A, email=EMAIL_A)

        def page(five_hour: float, weekly: float) -> str:
            s = AccountStanding(account, WindowStanding("five_hour", "running", five_hour, T0 + 3600, T0, False),
                                WindowStanding("seven_day", "current", weekly, T0 + 86400, T0, False),
                                WeeklyAnchor(T0 + 86400, exact=True), T0, True, True)
            return render_dashboard(self.ledger, self.registry, [s], recommend([s]), T0)

        def arcs(html: str) -> list[tuple[str, float]]:
            """Each ring's arc on the page, the weekly window's then the 5-hour window's: its colour, and the share
            of its ring it runs."""
            found = re.findall(r'<circle class="arc[^"]*"[^>]*stroke-dasharray="([\d.]+) ([\d.]+)"[^>]*'
                               r'style="color:([^"]+)"/>', html)
            return [(colour, round(float(run) / float(around), 2)) for run, around, colour in found]

        def figures(html: str) -> dict[str, tuple[str, str]]:
            """Each window's figure on the card, by the window's name: the class of its level's text colour, none
            below a warning, and the figure."""
            found = re.findall(r'</i>([^<]+)</span><span><b class="num(?: (l\d))?">([^<]+)</b>', html)
            return {name: (level, figure) for name, level, figure in found}

        # The 5-hour window warns from 80 % and errs from 95 %, the weekly window from 70 % and 90 %.
        html = page(75, 75)
        self.assertEqual(arcs(html), [("var(--warning)", 0.75), (rings.FIVE_HOUR, 0.75)])
        self.assertEqual(figures(html), {"Weekly": ("l1", "75%"), "5-hour": ("", "75%")})
        html = page(95, 89)
        self.assertEqual(arcs(html), [("var(--warning)", 0.89), ("var(--critical)", 0.95)])
        self.assertEqual(figures(html), {"Weekly": ("l1", "89%"), "5-hour": ("l2", "95%")})
        html = page(85, 92)
        self.assertEqual(arcs(html), [("var(--critical)", 0.92), ("var(--warning)", 0.85)])
        self.assertEqual(figures(html), {"Weekly": ("l2", "92%"), "5-hour": ("l1", "85%")})
        html = page(79, 69)
        self.assertEqual(arcs(html), [(rings.WEEKLY, 0.69), (rings.FIVE_HOUR, 0.79)])
        self.assertEqual(figures(html), {"Weekly": ("", "69%"), "5-hour": ("", "79%")})

    def test_the_style_sheet_is_written_from_the_palette(self):
        html = self.render()
        for colours in (palette.LIGHT, palette.DARK):
            for token, value in colours.items():
                self.assertIn(f"--{token}:{value};", html)

    def test_an_exact_weekly_reset_stays_exact_when_the_figure_is_estimated(self):
        exact = weekly_standing_of(Account(uuid=ACCOUNT_A, email=EMAIL_A), anchor_exact=True)
        html = render_dashboard(self.ledger, self.registry, [exact], recommend([exact]), T0)
        self.assertIn("≈62%", html)
        self.assertNotIn("resets ≈", html)
        inferred = weekly_standing_of(Account(uuid=ACCOUNT_A, email=EMAIL_A), anchor_exact=False)
        html = render_dashboard(self.ledger, self.registry, [inferred], recommend([inferred]), T0)
        self.assertIn("resets ≈", html)


def weekly_standing_of(account: Account, *, anchor_exact: bool) -> AccountStanding:
    """An account whose weekly figure is estimated (a rise since its reading) and whose schedule is exact or not."""
    reset = T0 + 3 * 86400
    return AccountStanding(account,
                           WindowStanding("five_hour", "not_started", 0.0, None, T0 - 7200, False),
                           WindowStanding("seven_day", "current", 62.0, reset, T0 - 3600, True),
                           WeeklyAnchor(reset - 7 * 86400, exact=anchor_exact), T0 - 600, True, True)


class ApproximateResetTest(unittest.TestCase):
    """A weekly reset time is approximate only when its schedule was inferred, whatever the figure's estimate."""

    def test_the_recommendation_marks_only_an_inferred_reset(self):
        account = Account(uuid=ACCOUNT_A, email=EMAIL_A)
        self.assertNotIn("≈", recommend([weekly_standing_of(account, anchor_exact=True)]).reason)
        self.assertIn("(≈", recommend([weekly_standing_of(account, anchor_exact=False)]).reason)

    def test_the_status_command_marks_only_an_inferred_reset(self):
        from windowtally.__main__ import format_status
        weekly = {"state": "current", "percent": 62.0, "resetsAt": "2026-10-25T22:00:00.000Z", "asOf": None,
                  "estimated": True, "exhaustsAt": None, "anchorExact": True}
        doc = {"generatedAt": "2026-10-20T10:00:00.000Z", "sourceErrors": [], "cliCondition": None,
               "recommended": {"account": None, "reason": "—", "reliefAt": None},
               "accounts": [{"label": "alpha", "isDesktop": False, "isCli": False, "subscription": None,
                             "fiveHour": {"state": "not_started", "percent": 0, "resetsAt": None, "estimated": False},
                             "weekly": weekly}]}
        self.assertRegex(format_status(doc), r"weekly : ≈62%, resets [A-Z][a-z]{2} ")
        doc["accounts"][0]["weekly"] = dict(weekly, anchorExact=False)
        self.assertIn("weekly : ≈62%, resets ≈", format_status(doc))


if __name__ == "__main__":
    unittest.main()
