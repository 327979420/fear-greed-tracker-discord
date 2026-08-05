import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fear_greed_bot import (  # noqa: E402
    build_discord_payload,
    change_text,
    classify_score,
    market_commentary,
    parse_snapshot,
)


SAMPLE = {
    "fear_and_greed": {
        "score": 72.4,
        "rating": "greed",
        "timestamp": "2026-08-05T01:30:00+00:00",
        "previous_close": 68.0,
        "previous_1_week": 61.2,
        "previous_1_month": 55.0,
        "previous_1_year": 44.0,
    }
}


class FearGreedBotTests(unittest.TestCase):
    def test_parse_snapshot(self):
        snapshot = parse_snapshot(SAMPLE)
        self.assertEqual(snapshot.score, 72.4)
        self.assertEqual(snapshot.rating, "greed")
        self.assertEqual(snapshot.previous_close, 68.0)

    def test_classification_boundaries(self):
        self.assertEqual(classify_score(10), "extreme fear")
        self.assertEqual(classify_score(35), "fear")
        self.assertEqual(classify_score(50), "neutral")
        self.assertEqual(classify_score(65), "greed")
        self.assertEqual(classify_score(90), "extreme greed")

    def test_change_text(self):
        self.assertEqual(change_text(72.4, 68.0), "↑ 4.4")
        self.assertEqual(change_text(68.0, 72.4), "↓ 4.4")
        self.assertEqual(change_text(50.0, None), "暂无对比")

    def test_payload_is_discord_embed(self):
        snapshot = parse_snapshot(SAMPLE)
        payload = build_discord_payload(snapshot)
        self.assertEqual(len(payload["embeds"]), 1)
        self.assertIn("72.4 / 100", payload["embeds"][0]["description"])
        self.assertIn("贪婪", payload["embeds"][0]["description"])
        self.assertEqual(len(payload["embeds"][0]["fields"]), 4)

    def test_commentary(self):
        snapshot = parse_snapshot(SAMPLE)
        text = market_commentary(snapshot)
        self.assertIn("风险偏好", text)
        self.assertIn("继续改善", text)


if __name__ == "__main__":
    unittest.main()
