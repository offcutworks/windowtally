"""The usage tables' context section: the responses by the size of their request's context, and the responses that
wrote their context to the cache again after a pause, with what writing the earlier context again cost beyond reading
it.

Every count is invented. Four sessions on one account, over a span of days:

- s1's main stream writes 50K to the 1-hour cache, then 100K a minute later, then after two hours reads 1K and writes
  150K — the cache had expired, a rewrite of the earlier request's 150K less the 1K read — then 400 seconds later
  reads 300K and writes 10K, which reads more than it writes;
- s1's subagent starts ten seconds after that with a 600K write to the 5-minute cache, its own first response and no
  rewrite, then writes 600K again 1,000 seconds later, a rewrite;
- s2 writes 100K to the 5-minute cache 299 seconds after its first response, inside that cache's lifetime;
- s3 writes to the 1-hour cache and, ten minutes on, a large result: more written than read, but the cache lived;
- s4 uses a model with no list price, so its pause and rewrite are neither priced nor counted.
"""

import unittest

from fixtures import ACCOUNT_A, EMAIL_A, ORG_A, Machine, assistant_lines, bridge_line, epoch
from windowtally import dashboard, history
from windowtally.pricing import cache_write_premium, response_cost
from windowtally.service import run_pass
from windowtally_gui import history_model
from windowtally_gui.history_model import Heading, Note, Table

NOW = epoch("2026-10-21T18:30:00Z")
T0 = NOW - 2 * 86400.0
OPUS = "claude-opus-5-5"
UNPRICED = "claude-unknown-9"

# (session, agent, model, t, cache read, 1-hour write, 5-minute write)
RESPONSES = (
    ("s1", None, OPUS, T0, 0, 50_000, 0),
    ("s1", None, OPUS, T0 + 60, 50_000, 100_000, 0),
    ("s1", None, OPUS, T0 + 60 + 7200, 1_000, 150_000, 0),
    ("s1", None, OPUS, T0 + 60 + 7200 + 400, 300_000, 0, 10_000),
    ("s1", "a1", OPUS, T0 + 60 + 7200 + 410, 0, 0, 600_000),
    ("s1", "a1", OPUS, T0 + 60 + 7200 + 1410, 0, 0, 600_000),
    ("s2", None, OPUS, T0 + 86400, 0, 0, 20_000),
    ("s2", None, OPUS, T0 + 86400 + 299, 0, 0, 100_000),
    ("s3", None, OPUS, T0 + 86400 + 5000, 0, 30_000, 0),
    ("s3", None, OPUS, T0 + 86400 + 5600, 30_000, 50_000, 0),
    ("s4", None, UNPRICED, T0 + 86400 + 9000, 0, 0, 10_000),
    ("s4", None, UNPRICED, T0 + 86400 + 10000, 0, 0, 20_000),
)
INPUT = 2


def cost_of(read: int, write_1h: int, write_5m: int) -> float:
    return response_cost(OPUS, input_tokens=INPUT, output_tokens=120, cache_read_tokens=read,
                         cache_write_5m_tokens=write_5m, cache_write_1h_tokens=write_1h)


class PremiumTest(unittest.TestCase):
    def test_a_write_costs_its_rate_less_a_read_s_at_each_lifetime(self):
        # claude-opus-5-5: $4 input, $0.20 cache read; a 1-hour write 2x input, a 5-minute write 1.25x.
        self.assertAlmostEqual(cache_write_premium(OPUS, prompt_tokens=0, cache_write_5m_tokens=0,
                                                   cache_write_1h_tokens=1_000_000), 7.8, places=9)
        self.assertAlmostEqual(cache_write_premium(OPUS, prompt_tokens=0, cache_write_5m_tokens=1_000_000,
                                                   cache_write_1h_tokens=0), 4.8, places=9)

    def test_fast_mode_doubles_and_an_unpriced_model_has_none(self):
        self.assertAlmostEqual(cache_write_premium(OPUS, prompt_tokens=0, cache_write_5m_tokens=1_000_000,
                                                   cache_write_1h_tokens=0, speed="fast"), 9.6, places=9)
        self.assertIsNone(cache_write_premium("claude-unknown-9", prompt_tokens=0, cache_write_5m_tokens=1,
                                              cache_write_1h_tokens=0))

    def test_the_tier_is_the_whole_context_s(self):
        # claude-haiku-5-5: $0.10 input and $0.01 read up to 100K of context, $0.50 and $0.05 above it.
        self.assertAlmostEqual(cache_write_premium("claude-haiku-5-5", prompt_tokens=50_000, cache_write_5m_tokens=40_000,
                                                   cache_write_1h_tokens=0), 40_000 * 0.115 / 1e6, places=12)
        self.assertAlmostEqual(cache_write_premium("claude-haiku-5-5", prompt_tokens=150_000,
                                                   cache_write_5m_tokens=40_000, cache_write_1h_tokens=0),
                               40_000 * 0.575 / 1e6, places=12)


class LabelsTest(unittest.TestCase):
    def test_every_range_is_named_by_its_edges(self):
        self.assertEqual([history.context_label(i) for i in range(len(history.CONTEXT_EDGES) + 1)],
                         ["under 100K", "100K–200K", "200K–500K", "500K and over"])

    def test_the_rewrites_are_said_in_one_sentence(self):
        self.assertEqual(history.rewrite_text(history.Rewrites(0, 0.0, 0.0)), "Rewritten after a pause: none.")
        self.assertEqual(history.rewrite_text(history.Rewrites(1, 4.05, 2.25)),
                         "Rewritten after a pause: 1 response, $4.05 beyond reading the context again (2.2% of the cost).")


class ContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machine = m = Machine()
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        streams: dict[tuple[str, str | None], list[dict]] = {}
        for i, (session, agent, model, t, read, write_1h, write_5m) in enumerate(RESPONSES):
            streams.setdefault((session, agent), []).extend(assistant_lines(
                f"m{i}", t, session, model=model, input_tokens=INPUT, cache_read=read, cache_write_1h=write_1h,
                cache_write_5m=write_5m, agent_id=agent))
        for (session, agent), lines in streams.items():
            m.transcript(session, ([] if agent else [bridge_line(session, ACCOUNT_A, ORG_A)]) + lines, agent=agent)
        run_pass(m.paths, now=NOW, dashboard=True)
        cls.h = history_model.compute(m.paths, "30d", now=NOW)
        cls.rows = {r.label: r for r in cls.h.usage.context}

    @classmethod
    def tearDownClass(cls):
        cls.machine.close()

    def test_each_response_stands_in_the_range_of_its_request_s_context(self):
        self.assertEqual(list(self.rows), ["under 100K", "100K–200K", "200K–500K", "500K and over", "In all"])
        self.assertEqual({label: (r.responses, r.sessions) for label, r in self.rows.items()},
                         {"under 100K": (6, 4), "100K–200K": (3, 2), "200K–500K": (1, 1), "500K and over": (2, 1),
                          "In all": (12, 4)})
        sent = {label: sum(INPUT + read + w1 + w5 for *_k, read, w1, w5 in RESPONSES
                           if history.context_label(sum(INPUT + read + w1 + w5 >= e for e in history.CONTEXT_EDGES))
                           == label) for label in self.rows if label != "In all"}
        for label, tokens in sent.items():
            self.assertEqual(self.rows[label].context, tokens, label)
        self.assertEqual(self.rows["In all"].context, sum(sent.values()))

    def test_the_cost_shares_and_the_mean_follow_the_priced_responses(self):
        biggest = self.rows["500K and over"]
        self.assertAlmostEqual(biggest.cost, 2 * cost_of(0, 0, 600_000))
        self.assertAlmostEqual(biggest.per_response, cost_of(0, 0, 600_000))
        smallest = self.rows["under 100K"]                       # four of its six responses priced
        priced = [cost_of(read, w1, w5) for _s, _a, model, t, read, w1, w5 in RESPONSES
                  if model == OPUS and INPUT + read + w1 + w5 < history.CONTEXT_EDGES[0]]
        self.assertEqual(len(priced), 4)
        self.assertAlmostEqual(smallest.cost, sum(priced))
        self.assertAlmostEqual(smallest.per_response, sum(priced) / 4)
        total = self.rows["In all"]
        self.assertAlmostEqual(total.cost, sum(cost_of(read, w1, w5) for _s, _a, model, _t, read, w1, w5 in RESPONSES
                                               if model == OPUS))
        self.assertAlmostEqual(total.cost, self.h.summary.api)
        self.assertAlmostEqual(sum(r.share for label, r in self.rows.items() if label != "In all"), 100.0)
        self.assertAlmostEqual(total.share, 100.0)

    def test_a_rewrite_follows_a_pause_and_writes_more_than_it_reads(self):
        # s1's 150K after two hours, of which the earlier request's 150,002 less the 1K read is written again at the
        # 1-hour rate, and the subagent's second 600K, all of it again, at the 5-minute rate. Not the subagent's first
        # response, nor the 10K that read 300K, nor s2's 100K 299 seconds on, nor s3's write ten minutes into an hour's
        # cache, nor s4's, which has no price.
        r = self.h.usage.rewrites
        premium = 149_002 * 7.8 / 1e6 + 600_000 * 4.8 / 1e6
        self.assertEqual(r.responses, 2)
        self.assertAlmostEqual(r.premium, premium)
        self.assertAlmostEqual(r.share, premium / self.rows["In all"].cost * 100)

    def test_the_window_shows_the_table_its_total_in_bold_and_the_rewrites_beneath(self):
        blocks = history_model._usage_blocks(self.h.usage)
        at = next(i for i, b in enumerate(blocks) if isinstance(b, Heading) and b.text == history.CONTEXT_HEADING)
        heading, table, note = blocks[at:at + 3]
        self.assertEqual(heading.hint, history.CONTEXT_NOTE)
        self.assertIsInstance(table, Table)
        self.assertEqual([c for c, _a in table.columns], list(history.CONTEXT_COLUMNS))
        self.assertEqual([a for _c, a in table.columns], ["w"] + ["e"] * (len(history.CONTEXT_COLUMNS) - 1))
        self.assertEqual(table.rows[-1], history.context_cells(self.rows["In all"]))
        self.assertEqual(table.totals, (len(table.rows) - 1,))
        self.assertEqual(note, Note(history.rewrite_text(self.h.usage.rewrites)))

    def test_the_page_and_the_export_show_the_same(self):
        page = dashboard.render_history(self.h)
        self.assertIn(history.CONTEXT_HEADING, page)
        self.assertIn("<b>In all</b>", page)
        self.assertIn(history.rewrite_text(self.h.usage.rewrites), page)
        self.assertIn('<td class="l">100K–200K</td>', page)
        for cell in history.context_cells(self.rows["100K–200K"])[1:]:
            self.assertIn(f"<td>{cell}</td>", page)

    def test_an_empty_span_has_no_rows_and_no_rewrites(self):
        empty = history_model.compute(self.machine.paths, "7d", now=NOW + 30 * 86400.0)
        self.assertEqual(empty.usage.context, ())
        self.assertEqual(empty.usage.rewrites, history.Rewrites(0, 0.0, 0.0))
        blocks = history_model._usage_blocks(empty.usage)
        table = next(b for b in blocks if isinstance(b, Table) and b.columns[0][0] == history.CONTEXT_COLUMNS[0])
        self.assertEqual((table.rows, table.totals), ((), ()))


if __name__ == "__main__":
    unittest.main()
