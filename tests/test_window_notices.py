"""The window's notifications: only what the desktop plugin never says — a relief, a stopped service, a renewal, a
standing source problem — each said once, and the renewals and problems remembered across starts."""

import json
import unittest
from dataclasses import replace
from pathlib import Path

from fixtures import ACCOUNT_A, EMAIL_A, epoch, iso, status_account, status_document, status_subscription
from windowtally_gui.live_model import STALE_AFTER
from windowtally_gui.notices_model import Notices
from windowtally_gui.state_model import WindowState
from windowtally_gui.status_model import snapshot_of

T0 = epoch("2026-10-20T10:00:00Z")


def subscription(**changes) -> dict:
    return status_subscription(**changes)


def account(plan=None) -> dict:
    return status_account(ACCOUNT_A, EMAIL_A, at=T0, plan=plan)


def document(accounts=None, **changes) -> dict:
    return status_document(accounts if accounts is not None else [account()], at=T0, **changes)


def snapshot(doc: dict):
    return snapshot_of(Path("status.json"), json.dumps(doc))


def blocked() -> dict:
    return document(recommended={"account": None, "reason": "Every account is at its limit.",
                                 "reliefAt": iso(T0 + 600)})


class NoticesTest(unittest.TestCase):
    def setUp(self):
        self.notices = Notices(started=T0)
        self.state = WindowState()

    def status(self, doc: dict):
        said, self.state = self.notices.on_status(snapshot(doc), self.state)
        return said

    def test_no_threshold_warning_is_ever_raised(self):
        # The plugin warns as the account in use crosses its limits; the window never does.
        hot = document(accounts=[account(plan=None)])
        for _ in range(3):
            self.assertEqual(self.status(hot), [])

    def test_a_relief_is_said_once_when_an_account_opens_after_all_were_at_their_limit(self):
        self.assertEqual(self.status(blocked()), [])
        self.assertEqual(self.status(blocked()), [])
        (notice,) = self.status(document())
        self.assertEqual((notice.kind, notice.title, notice.message), ("relief", "alpha can be used again",
                                                                       "alpha has room left."))
        self.assertEqual(self.status(document()), [])

    def test_a_renewal_is_said_once_per_period_and_not_again_after_a_restart(self):
        due = document(accounts=[account(plan=subscription(renewSoon=True, daysLeft=2))])
        (notice,) = self.status(due)
        self.assertEqual((notice.kind, notice.title), ("renewal", "alpha: the plan ends in 2 days"))
        self.assertIn("paid until Sat 7 Nov", notice.message)
        self.assertEqual(self.status(due), [])
        restarted = Notices(started=T0 + 86400)
        said, _ = restarted.on_status(snapshot(due), self.state)
        self.assertEqual(said, [], "remembered in the window's record")
        renewed = document(accounts=[account(plan=subscription(paidUntil="2026-12-07"))])
        self.status(renewed)
        self.assertEqual(self.state.renewals_notified, ())
        next_period = document(accounts=[account(plan=subscription(renewSoon=True, daysLeft=1,
                                                                   paidUntil="2026-12-07"))])
        self.assertEqual([n.kind for n in self.status(next_period)], ["renewal"])

    def test_a_source_problem_is_said_once_it_stood_through_two_status_files(self):
        troubled = document(sourceErrors=["bills: x.csv does not exist"])
        self.assertEqual(self.status(troubled), [], "one pass's blip is not said")
        (notice,) = self.status(troubled)
        self.assertEqual((notice.kind, notice.title, notice.message),
                         ("problem", "A new source problem", "bills: x.csv does not exist"))
        self.assertEqual(self.status(troubled), [])
        restarted = Notices(started=T0)
        restarted.on_status(snapshot(troubled), self.state)
        said, _ = restarted.on_status(snapshot(troubled), self.state)
        self.assertEqual(said, [], "a standing problem already said is not said at the next start")
        self.status(document())
        self.assertEqual(self.state.problems_notified, (), "a problem that cleared is forgotten")

    def test_a_stopped_service_is_said_once_counted_from_the_window_s_start(self):
        old = snapshot(document(generatedAt=iso(T0 - 3 * 3600)))
        self.assertEqual(self.notices.on_clock(old, T0 + 60), [], "a status from before the start is not a stop")
        (notice,) = self.notices.on_clock(old, T0 + STALE_AFTER + 1)
        self.assertEqual(notice.kind, "stopped")
        self.assertIn("Is the WindowTally service running?", notice.message)
        self.assertEqual(self.notices.on_clock(old, T0 + STALE_AFTER + 60), [])
        fresh = snapshot(document(generatedAt=iso(T0 + STALE_AFTER + 100)))
        self.assertEqual(self.notices.on_clock(fresh, T0 + STALE_AFTER + 110), [])
        later = T0 + 2 * STALE_AFTER + 200
        self.assertEqual([n.kind for n in self.notices.on_clock(fresh, later)], ["stopped"], "a new stop is said")

    def test_a_missing_status_is_a_stop_but_another_version_is_the_window_s_own_trouble(self):
        from windowtally_gui.status_model import Snapshot
        missing = Snapshot("missing", Path("status.json"))
        self.assertEqual([n.kind for n in self.notices.on_clock(missing, T0 + STALE_AFTER + 1)], ["stopped"])
        other = Notices(started=T0)
        self.assertEqual(other.on_clock(snapshot(dict(document(), v=2)), T0 + STALE_AFTER + 1), [])

    def test_the_record_survives_the_window_s_own_round_trip(self):
        from fixtures import Machine
        from windowtally_gui.state_model import load_state, save_state
        machine = Machine()
        try:
            state = replace(WindowState(), geometry="800x600+-1200+40", keep_on_top=True,
                            renewals_notified=(f"{ACCOUNT_A} 2026-11-07",), problems_notified=("bills: x",))
            save_state(machine.paths.window_state, state)
            self.assertEqual(load_state(machine.paths.window_state), (state, None))
            machine.paths.window_state.write_text("{", encoding="utf-8")
            restored, problem = load_state(machine.paths.window_state)
            self.assertEqual(restored, WindowState())
            self.assertIn("could not be read", problem)
        finally:
            machine.close()


class PlaceTest(unittest.TestCase):
    def test_a_remembered_place_on_a_monitor_attached_now_is_kept_and_cut_to_fit(self):
        from windowtally_gui.state_model import Area, fitted_geometry
        main, left = Area(0, 0, 1920, 1040), Area(-1280, 0, 0, 984)
        self.assertEqual(fitted_geometry("800x600+-1200+40", (main, left), (900, 700)), "800x600+-1200+40")
        self.assertEqual(fitted_geometry("2400x600+100+40", (main,), (900, 700)), "1920x600+0+40")
        self.assertEqual(fitted_geometry("800x600+-1200+40", (main,), (900, 700)), "900x700+510+113",
                         "a monitor gone: the default, centred on the main one")
        self.assertEqual(fitted_geometry(None, (main,), (900, 700)), "900x700+510+113")


if __name__ == "__main__":
    unittest.main()
