"""ingest_transcripts: responses, owners and prompts read from Claude Code transcripts, incrementally."""

import unittest

from fixtures import ACCOUNT_A, ORG_A, Machine, assistant_lines, bridge_line, epoch, user_line
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger

T0 = epoch("2026-10-20T10:00:00Z")


class TranscriptIngestTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def ingest(self):
        return ingest_transcripts(self.ledger, self.machine.paths.projects_dir)

    def responses(self):
        return self.ledger.db.execute(
            "SELECT message_id, t, session_id, agent_id, model, effort, output_tokens, thinking_tokens, "
            "cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens, entrypoint FROM responses "
            "ORDER BY message_id").fetchall()

    def test_one_row_per_response_with_its_final_usage_and_first_time(self):
        self.machine.transcript("s1", assistant_lines("msg_1", T0, "s1", outputs=(8, 8, 469)))
        self.ingest()
        rows = self.responses()
        self.assertEqual(len(rows), 1)
        message_id, t, session, agent, model, effort, output, thinking, read, write_5m, write_1h, entry = rows[0]
        self.assertEqual((message_id, session, agent, model, effort), ("msg_1", "s1", None, "claude-opus-5-5", "xhigh"))
        self.assertEqual(output, 469)
        self.assertEqual(t, T0)
        self.assertEqual((thinking, read, write_5m, write_1h, entry), (40, 1000, 0, 500, "claude-desktop"))

    def test_synthetic_messages_carry_no_usage(self):
        self.machine.transcript("s1", assistant_lines("msg_1", T0, "s1", model="<synthetic>"))
        self.ingest()
        self.assertEqual(self.responses(), [])

    def test_reads_only_new_complete_lines(self):
        path = self.machine.transcript("s1", assistant_lines("msg_1", T0, "s1"))
        self.assertEqual(self.ingest().responses, 2)
        partial = '{"type":"assistant","timestamp":"2026-10-20T10:05:00.000Z"'
        self.machine.transcript("s1", assistant_lines("msg_2", T0 + 60, "s1"), append=True, raw_tail=partial)
        second = self.ingest()
        self.assertEqual(second.responses, 2, "only msg_2's two complete lines are new")
        self.assertEqual([r[0] for r in self.responses()], ["msg_1", "msg_2"])
        cursor = self.ledger.cursor(str(path))
        self.assertEqual(cursor.offset, path.stat().st_size - len(partial), "the partial line is left for later")

    def test_a_shrunk_file_is_read_again_without_duplicates(self):
        self.machine.transcript("s1", assistant_lines("msg_1", T0, "s1") + assistant_lines("msg_2", T0 + 60, "s1"))
        self.ingest()
        self.machine.transcript("s1", assistant_lines("msg_1", T0, "s1"))
        self.ingest()
        self.assertEqual([r[0] for r in self.responses()], ["msg_1", "msg_2"])

    def test_owner_prompts_and_subagents(self):
        lines = [bridge_line("s1", ACCOUNT_A.upper(), ORG_A), user_line("s1", "p1", T0),
                 user_line("s1", "p1", T0 + 5), user_line("s1", "p2", T0 + 30)] + assistant_lines("msg_1", T0, "s1")
        self.machine.transcript("s1", lines)
        self.machine.transcript("s1", [user_line("s1", "p3", T0 + 40, sidechain=True)]
                                + assistant_lines("msg_sub", T0 + 41, "s1", agent_id="a1"), agent="a1")
        self.ingest()
        owners = self.ledger.db.execute("SELECT session_id, account_uuid FROM session_owners").fetchall()
        self.assertEqual(owners, [("s1", ACCOUNT_A)])
        prompts = self.ledger.db.execute("SELECT prompt_id, t FROM prompts ORDER BY prompt_id").fetchall()
        self.assertEqual(prompts, [("p1", T0), ("p2", T0 + 30)], "one row per prompt; a subagent's turns are not prompts")
        sub = [r for r in self.responses() if r[0] == "msg_sub"][0]
        self.assertEqual((sub[2], sub[3]), ("s1", "a1"))

    def test_cache_writes_without_a_ttl_breakdown_count_as_five_minute(self):
        self.machine.transcript("s1", assistant_lines("msg_1", T0, "s1", cache_write_1h=300, breakdown=False))
        self.ingest()
        self.assertEqual(self.responses()[0][9:11], (300, 0))

    def test_cost_is_recorded(self):
        self.machine.transcript("s1", assistant_lines("msg_1", T0, "s1", outputs=(1_000_000,), input_tokens=0,
                                                       cache_read=0, cache_write_1h=0))
        self.ingest()
        cost = self.ledger.db.execute("SELECT cost_usd FROM responses").fetchone()[0]
        self.assertAlmostEqual(cost, 20.0, places=9)  # claude-opus-5-5 output: $20 per million


if __name__ == "__main__":
    unittest.main()
