"""attribution: which account each response and reading belongs to."""

import unittest

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bridge_line,
                      epoch, iso)
from windowtally.accounts import by_org, load_registry
from windowtally.attribution import attribute
from windowtally.ingest_app_history import ingest_app_history
from windowtally.ingest_readings import ingest_readings
from windowtally.ingest_sync import ingest_sync_events
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger
from windowtally.service import run_pass

T0 = epoch("2026-10-20T10:00:00Z")


class AttributionTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.registry, _ = load_registry(self.machine.paths.accounts_dir)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def ingest(self):
        paths = self.machine.paths
        ingest_sync_events(self.ledger, paths.sync_events)
        ingest_app_history(self.ledger, paths.plan_usage_history, by_org(self.registry))
        ingest_readings(self.ledger, paths.readings_dir, now=T0)
        ingest_transcripts(self.ledger, paths.projects_dir)
        attribute(self.ledger)

    def account_of(self, message_id):
        return self.ledger.db.execute("SELECT account_uuid, account_source FROM responses WHERE message_id=?",
                                      (message_id,)).fetchone()

    def test_an_owned_session_and_its_subagents(self):
        self.machine.transcript("s1", [bridge_line("s1", ACCOUNT_A, ORG_A)] + assistant_lines("m1", T0, "s1"))
        self.machine.transcript("s1", assistant_lines("m2", T0 + 5, "s1", agent_id="x"), agent="x")
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_A, "owner"))
        self.assertEqual(self.account_of("m2"), (ACCOUNT_A, "owner"))

    def test_a_cli_session_follows_the_cli_timeline_and_falls_back_to_the_desktop(self):
        self.machine.app_history([(T0 - 600, ORG_B, 1, 10)])
        self.machine.sync_events([(T0 + 100, "cli_account", ACCOUNT_A)])
        self.machine.transcript("c1", assistant_lines("before", T0, "c1", entrypoint="sdk-cli")
                                + assistant_lines("after", T0 + 200, "c1", entrypoint="sdk-cli"))
        self.ingest()
        self.assertEqual(self.account_of("before"), (ACCOUNT_B, "desktop-timeline"))
        self.assertEqual(self.account_of("after"), (ACCOUNT_A, "cli-timeline"))

    def test_an_unowned_desktop_session_takes_the_app_account_of_its_moment(self):
        self.machine.app_history([(T0 - 600, ORG_A, 1, 10), (T0 + 600, ORG_B, 1, 10)])
        self.machine.transcript("d1", assistant_lines("early", T0, "d1") + assistant_lines("late", T0 + 900, "d1"))
        self.ingest()
        self.assertEqual(self.account_of("early"), (ACCOUNT_A, "desktop-timeline"))
        self.assertEqual(self.account_of("late"), (ACCOUNT_B, "desktop-timeline"))

    def test_an_owner_appearing_later_fills_in_until_a_timeline_answers(self):
        self.machine.transcript("s1", assistant_lines("m1", T0, "s1"))
        self.ingest()
        self.assertEqual(self.account_of("m1"), (None, None))
        self.machine.transcript("s1", [bridge_line("s1", ACCOUNT_A, ORG_A)], append=True)
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_A, "owner"))
        self.machine.app_history([(T0 - 600, ORG_B, 1, 10)])
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_B, "desktop-timeline"), "a timeline outranks the owner line")

    def test_a_timeline_answer_is_revised_when_an_event_arrives_later(self):
        self.machine.transcript("c1", assistant_lines("m1", T0, "c1", entrypoint="sdk-cli"))
        self.ingest()
        self.assertEqual(self.account_of("m1"), (None, None))
        self.machine.sync_events([(T0 - 10, "cli_account", ACCOUNT_B)])
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_B, "cli-timeline"))

    def test_a_session_with_two_owners_takes_the_desktop_account_among_them(self):
        self.machine.app_history([(T0 - 600, ORG_B, 1, 10)])
        self.machine.transcript("s1", [bridge_line("s1", ACCOUNT_A, ORG_A), bridge_line("s1", ACCOUNT_B, ORG_B)]
                                + assistant_lines("m1", T0, "s1"))
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_B, "desktop-timeline"))

    def test_a_reading_of_a_two_owner_session_takes_the_desktop_account_of_its_moment(self):
        third, third_org = "cccccccc-0000-4000-8000-000000000003", "0c0c0c0c-0000-4000-8000-00000000000c"
        self.machine.add_account(third, "gamma@example.com", third_org)
        self.registry, _ = load_registry(self.machine.paths.accounts_dir)
        self.machine.transcript("multi", [bridge_line("multi", ACCOUNT_A, ORG_A), bridge_line("multi", ACCOUNT_B, ORG_B)])
        self.machine.reading("multi", T0, (10, T0 + 3600), (50, T0 + 86400))
        self.machine.app_history([(T0 - 600, third_org, 1, 10)])
        self.ingest()
        accounts = {account for (account,) in self.ledger.db.execute(
            "SELECT account_uuid FROM observations WHERE source='plugin'")}
        self.assertEqual(accounts, {third}, "the app's account of the moment outranks the session's owner lines")

    def test_answers_follow_new_points_and_points_inserted_in_the_past(self):
        self.machine.app_history([(T0 - 600, ORG_A, 1, 10)])
        self.machine.transcript("d1", assistant_lines("r1", T0, "d1"))
        self.ingest()
        self.assertEqual(self.account_of("r1"), (ACCOUNT_A, "desktop-timeline"))
        self.machine.app_history([(T0 - 600, ORG_A, 1, 10), (T0 + 600, ORG_B, 1, 10)])
        self.machine.transcript("d1", assistant_lines("r2", T0 + 900, "d1"), append=True)
        self.ingest()
        self.assertEqual((self.account_of("r1"), self.account_of("r2")),
                         ((ACCOUNT_A, "desktop-timeline"), (ACCOUNT_B, "desktop-timeline")))
        self.machine.sync_events([(T0 - 300, "desktop_account", ACCOUNT_B)])
        self.ingest()
        self.assertEqual(self.account_of("r1"), (ACCOUNT_B, "desktop-timeline"), "a point in the past revisits r1")

    def test_readings_by_owner_before_any_timeline_then_by_weekly_reset_then_by_timeline(self):
        weekly_reset = epoch("2026-10-25T22:00:00Z")
        self.machine.transcript("owned", [bridge_line("owned", ACCOUNT_A, ORG_A)])
        self.machine.reading("owned", T0, (10, T0 + 3600), (50, weekly_reset))
        self.machine.reading("matched", T0 + 60, (11, T0 + 3600), (51, weekly_reset + 0.2))
        self.machine.reading("unknown", T0 + 120, (3, T0 + 7200), (20, weekly_reset - 86400))
        # The app's samples begin after the owned reading, which the owner line alone can then answer.
        self.machine.app_history([(T0 + 30, ORG_B, 1, 10)])
        self.ingest()
        rows = dict(((ref, kind), (account, source)) for ref, kind, account, source in self.ledger.db.execute(
            "SELECT ref, kind, account_uuid, account_source FROM observations WHERE source='plugin'"))
        self.assertEqual(rows[("owned", "seven_day")], (ACCOUNT_A, "owner"))
        self.assertEqual(rows[("matched", "five_hour")], (ACCOUNT_A, "fingerprint"))
        self.assertEqual(rows[("unknown", "seven_day")], (ACCOUNT_B, "desktop-timeline"))

    def readings(self):
        return {(ref, t, kind): (account, source) for ref, t, kind, account, source in self.ledger.db.execute(
            "SELECT ref, t, kind, account_uuid, account_source FROM observations WHERE source='plugin'")}

    def test_a_desktop_session_follows_the_app_through_a_switch(self):
        self.machine.sync_events([(T0 - 100, "desktop_account", ACCOUNT_A), (T0 + 300, "desktop_account", ACCOUNT_B)])
        self.machine.transcript("s1", [bridge_line("s1", ACCOUNT_A, ORG_A)] + assistant_lines("before", T0, "s1")
                                + assistant_lines("after", T0 + 400, "s1"))
        self.ingest()
        self.assertEqual(self.account_of("before"), (ACCOUNT_A, "desktop-timeline"))
        self.assertEqual(self.account_of("after"), (ACCOUNT_B, "desktop-timeline"), "the owner line names the old account")

    def test_a_session_opened_after_a_switch_naming_the_old_account_runs_on_the_new_one(self):
        self.machine.sync_events([(T0 - 3600, "desktop_account", ACCOUNT_A), (T0 - 300, "desktop_account", ACCOUNT_B)])
        self.machine.transcript("s2", [bridge_line("s2", ACCOUNT_A, ORG_A)] + assistant_lines("m1", T0, "s2"))
        self.machine.reading("s2", T0 + 60, (5, T0 + 3600), (7, T0 + 2 * 86400))
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_B, "desktop-timeline"))
        self.assertEqual(set(self.readings().values()), {(ACCOUNT_B, "desktop-timeline")})

    def test_the_desktop_timeline_names_no_account_while_the_app_is_at_its_sign_in_page(self):
        self.machine.sync_events([(T0 - 600, "desktop_account", ACCOUNT_A), (T0 - 100, "desktop_signed_out", ACCOUNT_A),
                                  (T0 + 300, "desktop_account", ACCOUNT_B)])
        self.machine.transcript("d1", assistant_lines("signed-in", T0 - 300, "d1")
                                + assistant_lines("signed-out", T0, "d1") + assistant_lines("after", T0 + 400, "d1"))
        self.machine.transcript("o1", [bridge_line("o1", ACCOUNT_A, ORG_A)] + assistant_lines("owned", T0 + 10, "o1"))
        self.ingest()
        self.assertEqual(self.account_of("signed-in"), (ACCOUNT_A, "desktop-timeline"))
        self.assertEqual(self.account_of("signed-out"), (None, None), "the account signed out of is not named")
        self.assertEqual(self.account_of("owned"), (ACCOUNT_A, "owner"), "only a session's own owner line answers then")
        self.assertEqual(self.account_of("after"), (ACCOUNT_B, "desktop-timeline"), "a sign-in ends the stretch")

        # The sign-out recorded after the first attribution revisits what it covers.
        self.machine.sync_events([(T0 + 350, "desktop_signed_out", ACCOUNT_B)])
        self.ingest()
        self.assertEqual(self.account_of("after"), (None, None))

    def test_the_owner_line_fills_in_before_the_timelines_begin(self):
        self.machine.sync_events([(T0 + 3600, "desktop_account", ACCOUNT_B)])
        self.machine.transcript("s3", [bridge_line("s3", ACCOUNT_A, ORG_A)] + assistant_lines("early", T0, "s3")
                                + assistant_lines("late", T0 + 4000, "s3"))
        self.ingest()
        self.assertEqual(self.account_of("early"), (ACCOUNT_A, "owner"))
        self.assertEqual(self.account_of("late"), (ACCOUNT_B, "desktop-timeline"))

    def test_an_owner_line_recorded_later_names_the_session_s_owner_anew(self):
        self.machine.transcript("s4", [bridge_line("s4", ACCOUNT_A, ORG_A)] + assistant_lines("m1", T0, "s4"))
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_A, "owner"))
        self.machine.transcript("s4", [bridge_line("s4", ACCOUNT_B, ORG_B)], append=True)
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_B, "owner"), "the owner line recorded last")

    def test_a_reading_on_another_account_s_weekly_schedule_is_that_account_s(self):
        alpha_reset, beta_reset = epoch("2026-10-25T22:00:00Z"), epoch("2026-10-24T05:00:00Z")
        self.machine.sync_events([(T0 - 600, "desktop_account", ACCOUNT_A), (T0 + 600, "desktop_account", ACCOUNT_B),
                                  (T0 + 1200, "desktop_account", ACCOUNT_A)])
        for index, t in enumerate((T0, T0 + 60, T0 + 120)):          # alpha's own readings, alpha's schedule
            self.machine.reading(f"a{index}", t, (10, T0 + 3600), (90, alpha_reset + 0.08 * index))
        for index, t in enumerate((T0 + 700, T0 + 760)):               # beta's own readings, beta's schedule
            self.machine.reading(f"b{index}", t, (3, T0 + 7200), (4, beta_reset - 0.05 * index))
        # The timeline says alpha again, but this reading carries beta's reset: the switch back was recorded early.
        self.machine.reading("late", T0 + 1300, (5, T0 + 7200), (5, beta_reset + 7 * 86400))
        # A reset on no account's schedule leaves the timeline's answer standing.
        self.machine.reading("moved", T0 + 1400, (11, T0 + 3600), (91, alpha_reset + 3 * 86400))
        self.ingest()
        rows = self.readings()
        self.assertEqual(rows[("late", T0 + 1300, "seven_day")], (ACCOUNT_B, "fingerprint"))
        self.assertEqual(rows[("late", T0 + 1300, "five_hour")], (ACCOUNT_B, "fingerprint"))
        self.assertEqual(rows[("moved", T0 + 1400, "seven_day")], (ACCOUNT_A, "desktop-timeline"))
        self.assertEqual(rows[("a1", T0 + 60, "seven_day")], (ACCOUNT_A, "desktop-timeline"))
        self.assertEqual(rows[("b0", T0 + 700, "seven_day")], (ACCOUNT_B, "desktop-timeline"))

    def test_a_cli_session_s_reading_follows_the_cli_timeline(self):
        self.machine.sync_events([(T0 - 600, "desktop_account", ACCOUNT_B), (T0 - 500, "cli_account", ACCOUNT_A)])
        self.machine.transcript("c1", assistant_lines("m1", T0, "c1", entrypoint="sdk-cli"))
        self.machine.reading("c1", T0 + 30, (5, T0 + 3600), (7, T0 + 2 * 86400))
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_A, "cli-timeline"))
        self.assertEqual(set(self.readings().values()), {(ACCOUNT_A, "cli-timeline")})

    def test_a_ledger_derived_under_another_rule_is_derived_again_whole(self):
        self.machine.sync_events([(T0 - 600, "desktop_account", ACCOUNT_A)])
        self.machine.transcript("s5", [bridge_line("s5", ACCOUNT_B, ORG_B)] + assistant_lines("m1", T0, "s5"))
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_A, "desktop-timeline"))
        with self.ledger.transaction():                              # as an earlier rule left it
            self.ledger.db.execute("UPDATE responses SET account_uuid=?, account_source='owner'", (ACCOUNT_B,))
            self.ledger.set_meta("attribution_rule", "1")
        self.ingest()
        self.assertEqual(self.account_of("m1"), (ACCOUNT_A, "desktop-timeline"))


class SwitchLivePathTest(unittest.TestCase):
    """The desktop app switches from alpha, at 98 % of its week, to beta while sessions naming alpha stay open."""

    def test_after_the_switch_each_account_shows_its_own_standing(self):
        machine = Machine()
        try:
            machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
            alpha_reset, beta_reset = T0 + 4 * 86400, T0 + 2.5 * 86400
            machine.sync_events([(T0 - 3600, "desktop_account", ACCOUNT_A), (T0, "desktop_account", ACCOUNT_B)])
            machine.transcript("open", [bridge_line("open", ACCOUNT_A, ORG_A)] + assistant_lines("m1", T0 - 1800, "open"))
            machine.reading("open", T0 - 1200, (40, T0 + 3600), (98, alpha_reset))
            run_pass(machine.paths, T0 - 1100, dashboard=False)
            machine.transcript("open", assistant_lines("m2", T0 + 600, "open"), append=True)
            machine.reading("open", T0 + 900, (4, T0 + 5 * 3600), (5, beta_reset))
            machine.transcript("later", [bridge_line("later", ACCOUNT_A, ORG_A)] + assistant_lines("m3", T0 + 950, "later"))
            machine.reading("later", T0 + 1000, (6, T0 + 5 * 3600), (6, beta_reset))
            report = run_pass(machine.paths, T0 + 1200, dashboard=False)
            accounts = {a["label"]: a for a in report.status["accounts"]}
            self.assertEqual((accounts["alpha"]["weekly"]["percent"], accounts["alpha"]["weekly"]["resetsAt"]),
                             (98.0, iso(alpha_reset)))
            self.assertEqual((accounts["beta"]["weekly"]["percent"], accounts["beta"]["weekly"]["resetsAt"]),
                             (6.0, iso(beta_reset)))
            self.assertEqual(report.status["recommended"]["account"], ACCOUNT_B)
        finally:
            machine.close()


if __name__ == "__main__":
    unittest.main()
