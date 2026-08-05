import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fear_greed_bot import (  # noqa: E402
    build_payload,
    change_text,
    classify,
    marker_segment,
    parse_snapshot,
    render_card,
    zone_label,
)

SAMPLE = {
    "fear_and_greed": {
        "score": 58.2,
        "rating": "greed",
        "timestamp": "2026-08-05T00:00:00+00:00",
        "previous_close": 58.2,
        "previous_1_week": 34.7,
        "previous_1_month": 32.5,
    },
    "fear_and_greed_historical": {
        "data": [
            {"x": 1785542400000, "y": 31.0},
            {"x": 1785628800000, "y": 36.0},
            {"x": 1785715200000, "y": 45.0},
            {"x": 1785801600000, "y": 58.2},
        ]
    },
}


class FearGreedBotTests(unittest.TestCase):
    def test_parse_snapshot(self):
        snapshot = parse_snapshot(SAMPLE)
        self.assertEqual(snapshot.score, 58.2)
        self.assertEqual(snapshot.previous_close, 58.2)
        self.assertEqual(snapshot.previous_1_week, 34.7)
        self.assertEqual(len(snapshot.history), 4)

    def test_classification_boundaries(self):
        self.assertEqual(classify(24), "extreme fear")
        self.assertEqual(classify(44), "fear")
        self.assertEqual(classify(55), "neutral")
        self.assertEqual(classify(75), "greed")
        self.assertEqual(classify(76), "extreme greed")

    def test_change_text(self):
        self.assertEqual(change_text(58.2, 58.2), "→ 0.0")
        self.assertEqual(change_text(58.2, 34.7), "↑ 23.5")

    def test_payload_is_minimal(self):
        snapshot = parse_snapshot(SAMPLE)
        payload = build_payload(snapshot)
        self.assertEqual(payload["content"], "今日落入‘贪婪’区间：58.2")

    def test_marker_does_not_cross_center(self):
        x1, y1, x2, y2 = marker_segment((520, 520), 58.2)
        inner_distance = ((x1 - 520) ** 2 + (y1 - 520) ** 2) ** 0.5
        outer_distance = ((x2 - 520) ** 2 + (y2 - 520) ** 2) ** 0.5
        self.assertGreaterEqual(inner_distance, 237.9)
        self.assertGreater(outer_distance, inner_distance)

    def test_render_card(self):
        snapshot = parse_snapshot(SAMPLE)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "card.png"
            render_card(snapshot, str(output))
            self.assertTrue(output.exists())
            with Image.open(output) as image:
                self.assertEqual(image.size, (1600, 900))
                self.assertEqual(image.format, "PNG")

    def test_zone_label(self):
        self.assertEqual(zone_label(58.2), "贪婪")


if __name__ == "__main__":
    unittest.main()
