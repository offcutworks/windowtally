"""pricing: a response's API-equivalent cost at the published prices, as Claude Code's own cost record counts it."""

import unittest

import fixtures  # noqa: F401  (puts the tool folder on the import path)
from windowtally.pricing import canonical_model, price_for, response_cost


class ResponseCostTest(unittest.TestCase):
    def test_a_response_with_1_hour_cache_writes_at_the_published_rates(self):
        # claude-opus-5-5 at $4 input, $20 output and $0.20 cache read, its 1-hour writes at twice the input rate, the
        # rule Claude Code's own cost record follows (pricing). Invented counts: $0.0004 + $0.40 + $1.00 + $2.00.
        cost = response_cost("claude-opus-5-5", input_tokens=100, output_tokens=20_000, cache_read_tokens=5_000_000,
                             cache_write_5m_tokens=0, cache_write_1h_tokens=250_000)
        self.assertAlmostEqual(cost, 3.4004, places=7)

    def test_each_component_at_its_published_rate(self):
        # claude-sonnet-5-5: $2 input, $10 output, $0.20 cache read; writes 1.25x (5 min) and 2x (1 h) input.
        million = 1_000_000
        cases = {
            "input": (dict(input_tokens=million), 2.0),
            "output": (dict(output_tokens=million), 10.0),
            "cache read": (dict(cache_read_tokens=million), 0.20),
            "5-minute write": (dict(cache_write_5m_tokens=million), 2.5),
            "1-hour write": (dict(cache_write_1h_tokens=million), 4.0),
        }
        for name, (tokens, expected) in cases.items():
            counts = dict(input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_5m_tokens=0,
                          cache_write_1h_tokens=0)
            counts.update(tokens)
            with self.subTest(name):
                self.assertAlmostEqual(response_cost("claude-sonnet-5-5", **counts), expected, places=9)

    def test_fast_mode_doubles(self):
        # claude-opus-5-5 fast mode is published at $8 / $40 per million.
        cost = response_cost("claude-opus-5-5", input_tokens=0, output_tokens=1_000_000, cache_read_tokens=0,
                             cache_write_5m_tokens=0, cache_write_1h_tokens=0, speed="fast")
        self.assertAlmostEqual(cost, 40.0, places=9)

    def test_haiku_long_context_tier(self):
        # claude-haiku-5-5: $0.10 per million input up to a 100K-token prompt, $0.50 above it.
        short = response_cost("claude-haiku-5-5", input_tokens=50_000, output_tokens=0, cache_read_tokens=0,
                              cache_write_5m_tokens=0, cache_write_1h_tokens=0)
        long = response_cost("claude-haiku-5-5", input_tokens=200_000, output_tokens=0, cache_read_tokens=0,
                             cache_write_5m_tokens=0, cache_write_1h_tokens=0)
        self.assertAlmostEqual(short, 0.005, places=9)
        self.assertAlmostEqual(long, 0.10, places=9)

    def test_unpriced_model_has_no_cost(self):
        self.assertIsNone(response_cost("claude-unknown-9", input_tokens=1, output_tokens=1, cache_read_tokens=0,
                                        cache_write_5m_tokens=0, cache_write_1h_tokens=0))


class CanonicalModelTest(unittest.TestCase):
    def test_strips_context_tag_and_date_snapshot(self):
        self.assertEqual(canonical_model("claude-opus-4-6[1m]"), "claude-opus-4-6")
        self.assertEqual(canonical_model("claude-sonnet-4-5-20250929"), "claude-sonnet-4-5")
        self.assertEqual(canonical_model("claude-opus-5-5"), "claude-opus-5-5")
        self.assertIsNotNone(price_for("claude-opus-4-6[1m]"))
        self.assertIsNone(canonical_model(None))


if __name__ == "__main__":
    unittest.main()
