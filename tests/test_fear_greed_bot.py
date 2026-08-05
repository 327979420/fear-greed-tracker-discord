import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fear_greed_bot import (  # noqa: E402
    build_discord_payload,
    change_text,
    classify_score,
    market_commentary,
    parse_snapshot,
    render_card,
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
    },
    "fear_and_greed_historical": {
        "data": [
            {"x": 1, "y": 54.0},
            {"x": 2, "y": 61.0},
            {"x": 3, "y": 72.4},
        ]
    },
}


class FearGreedBotTests(unittest.TestCase):
    def test_parse_snapshot_and_history(self):
        snapshot = parse_snapshot(SAMPLE)
        self.assertEqual(snapshot.score, 72.4)
        self.assertEqual(snapshot.rating, "greed")
        self.assertEqual(snapshot.previous_close, 68.0)
        self.assertEqual(len(snapshot.history), 3)
        self.assertEqual(snapshot.history[-1].score, 72.4)

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

    def test_payload_references_attached_image(self):
        snapshot = parse_snapshot(SAMPLE)
        payload = build_discord_payload(snapshot)
        self.assertEqual(len(payload["embeds"]), 1)
        self.assertEqual(
            payload["embeds"][0]["image"]["url"],
            "attachment://fear-greed-card.png",
        )
        self.assertIn("贪婪 72.4", payload["content"])

    def test_render_card_creates_png(self):
        snapshot = parse_snapshot(SAMPLE)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "card.png"
            render_card(snapshot, str(output))
            self.assertTrue(output.exists())
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1200, 675))

    def test_commentary(self):
        snapshot = parse_snapshot(SAMPLE)
        text = market_commentary(snapshot)
        self.assertIn("风险偏好", text)
        self.assertIn("继续改善", text)


if __name__ == "__main__":
    unittest.main()
