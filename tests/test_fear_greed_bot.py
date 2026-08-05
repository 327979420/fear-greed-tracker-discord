import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fear_greed_bot import (  # noqa: E402
    build_payload,
    change_text,
    classify,
    objective_comment,
    parse_snapshot,
    render_card,
    zone_label,
)

SAMPLE = {
    "fear_and_greed": {
        "score": 72.4,
        "rating": "greed",
        "timestamp": "2026-08-05T00:30:00+00:00",
        "previous_close": 68.0,
        "previous_1_week": 59.3,
        "previous_1_month": 44.7,
    },
    "fear_and_greed_historical": {
        "data": [
            {"x": 1785542400000, "y": 44.7},
            {"x": 1786147200000, "y": 51.0},
            {"x": 1786752000000, "y": 59.3},
            {"x": 1787356800000, "y": 65.1},
            {"x": 1787961600000, "y": 68.0},
            {"x": 1788566400000, "y": 72.4},
        ]
    },
}


class FearGreedBotTests(unittest.TestCase):
    def test_parse_snapshot(self):
        snapshot = parse_snapshot(SAMPLE)
        self.assertEqual(snapshot.score, 72.4)
        self.assertEqual(len(snapshot.history), 6)

    def test_official_ranges(self):
        self.assertEqual(classify(24), "extreme fear")
        self.assertEqual(classify(44), "fear")
        self.assertEqual(classify(55), "neutral")
        self.assertEqual(classify(75), "greed")
        self.assertEqual(classify(76), "extreme greed")

    def test_labels_include_zone_information(self):
        self.assertEqual(zone_label(68), "贪婪")
        self.assertEqual(zone_label(44.7), "中性")

    def test_change_text(self):
        self.assertEqual(change_text(72.4, 68.0), "↑ 4.4")

    def test_objective_commentary(self):
        self.assertEqual(
            objective_comment(parse_snapshot(SAMPLE)),
            "市场情绪处于贪婪区间，风险偏好较高。",
        )

    def test_payload(self):
        self.assertIn("72.4", build_payload(parse_snapshot(SAMPLE))["content"])

    def test_render_card(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "card.png")
            render_card(parse_snapshot(SAMPLE), path)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 5000)


if __name__ == "__main__":
    unittest.main()
