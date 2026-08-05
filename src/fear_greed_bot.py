#!/usr/bin/env python3
"""Generate a live CNN Fear & Greed dashboard and publish it to Discord."""
from __future__ import annotations

import json
import math
import mimetypes
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
OUTPUT_PATH = os.getenv("OUTPUT_IMAGE_PATH", "/tmp/fear-greed-card.png")
TIMEOUT = 25
RETRIES = 3
BEIJING = timezone(timedelta(hours=8))

COLORS = {
    "bg": "#F6F7F9",
    "panel": "#FFFFFF",
    "border": "#E5E7EB",
    "text": "#111827",
    "muted": "#4B5563",
    "subtle": "#6B7280",
    "extreme fear": "#EF4444",
    "fear": "#F97316",
    "neutral": "#9CA3AF",
    "greed": "#22A447",
    "extreme greed": "#15803D",
    "extreme fear fill": "#FEE2E2",
    "fear fill": "#FFEDD5",
    "neutral fill": "#F3F4F6",
    "greed fill": "#E4F6E8",
    "extreme greed fill": "#DCFCE7",
}

ZONE_META = {
    "extreme fear": ("极度恐慌", "0–24"),
    "fear": ("恐慌", "25–44"),
    "neutral": ("中性", "45–55"),
    "greed": ("贪婪", "56–75"),
    "extreme greed": ("极度贪婪", "76–100"),
}


@dataclass(frozen=True)
class HistoryPoint:
    when: datetime
    score: float


@dataclass(frozen=True)
class Snapshot:
    score: float
    rating: str
    timestamp: datetime
    previous_close: float | None
    previous_1_week: float | None
    previous_1_month: float | None
    history: tuple[HistoryPoint, ...]


def _number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def classify(score: float) -> str:
    if score <= 24:
        return "extreme fear"
    if score <= 44:
        return "fear"
    if score <= 55:
        return "neutral"
    if score <= 75:
        return "greed"
    return "extreme greed"


def zone_label(score: float | None) -> str:
    return "暂无" if score is None else ZONE_META[classify(score)][0]


def zone_color(score: float | None) -> str:
    return COLORS["neutral"] if score is None else COLORS[classify(score)]


def zone_fill(score: float | None) -> str:
    return COLORS["neutral fill"] if score is None else COLORS[f"{classify(score)} fill"]


def format_score(value: float | None) -> str:
    if value is None:
        return "暂无"
    rounded = round(value, 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"


def change_text(current: float, previous: float | None) -> str:
    if previous is None:
        return "暂无"
    delta = current - previous
    if abs(delta) < 0.05:
        return "→ 0.0"
    return f"{'↑' if delta > 0 else '↓'} {abs(delta):.1f}"


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                number = float(text)
                if number > 10_000_000_000:
                    number /= 1000
                return datetime.fromtimestamp(number, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                pass
    return datetime.now(timezone.utc)


def _history(payload: dict[str, Any]) -> tuple[HistoryPoint, ...]:
    historical = payload.get("fear_and_greed_historical")
    rows: list[Any] = []
    if isinstance(historical, dict):
        for key in ("data", "history"):
            if isinstance(historical.get(key), list):
                rows = historical[key]
                break
    elif isinstance(historical, list):
        rows = historical

    points: list[HistoryPoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = None
        for key in ("y", "score", "value"):
            candidate = _number(row.get(key))
            if candidate is not None:
                score = candidate
                break
        raw_time = next((row.get(k) for k in ("x", "timestamp", "date") if row.get(k) is not None), None)
        if score is not None and raw_time is not None:
            points.append(HistoryPoint(_parse_datetime(raw_time), score))
    points.sort(key=lambda point: point.when)
    return tuple(points[-30:])


def fetch_json(url: str = API_URL) -> dict[str, Any]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        "User-Agent": "Mozilla/5.0 Chrome/126.0",
    }
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        try:
            request = Request(url, headers=headers, method="GET")
            with urlopen(request, timeout=TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise ValueError("CNN endpoint returned an unexpected response")
            return result
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt < RETRIES - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to fetch CNN Fear & Greed data: {last_error}")


def parse_snapshot(payload: dict[str, Any]) -> Snapshot:
    current = payload.get("fear_and_greed")
    if not isinstance(current, dict):
        raise ValueError("Missing fear_and_greed data")
    score = _number(current.get("score"))
    if score is None:
        raise ValueError("Missing current score")
    rating = str(current.get("rating") or classify(score)).strip().lower()
    if rating not in ZONE_META:
        rating = classify(score)
    timestamp = _parse_datetime(current.get("timestamp"))
    history = list(_history(payload))
    if not history or abs(history[-1].score - score) > 0.05:
        history.append(HistoryPoint(timestamp, score))
    return Snapshot(
        score=score,
        rating=rating,
        timestamp=timestamp,
        previous_close=_number(current.get("previous_close")),
        previous_1_week=_number(current.get("previous_1_week")),
        previous_1_month=_number(current.get("previous_1_month")),
        history=tuple(history[-30:]),
    )


def objective_comment(snapshot: Snapshot) -> str:
    label = ZONE_META[classify(snapshot.score)][0]
    if snapshot.score >= 56:
        return f"市场情绪处于{label}区间，风险偏好较高。"
    if snapshot.score <= 44:
        return f"市场情绪处于{label}区间，风险偏好较低。"
    return "市场情绪处于中性区间，风险偏好相对均衡。"


def _font_path(bold: bool) -> str | None:
    configured = os.getenv("FONT_BOLD" if bold else "FONT_REGULAR", "").strip()
    candidates = [configured] if configured else []
    candidates += [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    return next((item for item in candidates if item and Path(item).exists()), None)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    path = _font_path(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int = 24, fill: str = COLORS["panel"], outline: str = COLORS["border"], width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def centered(draw: ImageDraw.ImageDraw, center: tuple[float, float], text: str, text_font: ImageFont.ImageFont, fill: str) -> None:
    box = draw.textbbox((0, 0), text, font=text_font)
    draw.text((center[0] - (box[2] - box[0]) / 2, center[1] - (box[3] - box[1]) / 2), text, font=text_font, fill=fill)


def pill(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, score: float | None) -> None:
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=zone_fill(score))
    centered(draw, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, font(19, True), zone_color(score))


def render_card(snapshot: Snapshot, output_path: str = OUTPUT_PATH) -> str:
    width, height = 1600, 900
    image = Image.new("RGB", (width, height), COLORS["bg"])
    draw = ImageDraw.Draw(image)

    draw.text((36, 24), "美股 Fear & Greed 每日播报", font=font(52, True), fill=COLORS["text"])
    draw.text((38, 92), "基于 CNN Fear & Greed Index", font=font(23), fill=COLORS["muted"])
    updated = snapshot.timestamp.astimezone(BEIJING).strftime("%Y年%m月%d日 %H:%M（北京时间）")
    updated_box = draw.textbbox((0, 0), updated, font=font(22))
    draw.text((1562 - (updated_box[2] - updated_box[0]), 38), updated, font=font(22), fill=COLORS["text"])
    source = "数据来源：CNN Business"
    source_box = draw.textbbox((0, 0), source, font=font(21))
    draw.text((1562 - (source_box[2] - source_box[0]), 84), source, font=font(21), fill=COLORS["subtle"])

    meter_panel = (34, 128, 860, 744)
    rounded(draw, meter_panel, 26)
    cx, cy = 447, 535
    radius = 332

    def angle(score: float) -> float:
        return 180 - score * 1.8

    zone_segments = [(0, 24, "extreme fear"), (25, 44, "fear"), (45, 55, "neutral"), (56, 75, "greed"), (76, 100, "extreme greed")]
    for low, high, key in zone_segments:
        draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), start=angle(high), end=angle(low), fill=COLORS[key], width=40)

    for tick in range(0, 101, 5):
        a = math.radians(angle(tick))
        r1, r2 = 272, 250 if tick % 25 == 0 else 258
        draw.line((cx + math.cos(a) * r1, cy - math.sin(a) * r1, cx + math.cos(a) * r2, cy - math.sin(a) * r2), fill="#CBD5E1", width=2 if tick % 25 == 0 else 1)
        if tick % 25 == 0:
            centered(draw, (cx + math.cos(a) * 220, cy - math.sin(a) * 220), str(tick), font(17), COLORS["text"])

    labels = [(142, 402, "extreme fear"), (254, 246, "fear"), (447, 174, "neutral"), (642, 246, "greed"), (754, 402, "extreme greed")]
    for x, y, key in labels:
        label, score_range = ZONE_META[key]
        centered(draw, (x, y), label, font(21, True), COLORS[key])
        centered(draw, (x, y + 34), score_range, font(16), COLORS["text"])

    current_color = zone_color(snapshot.score)
    draw.ellipse((cx - 226, cy - 226, cx + 226, cy + 226), fill="#FFFFFF", outline="#F1F5F9", width=2)
    centered(draw, (cx, cy - 22), format_score(snapshot.score), font(108, True), current_color)
    centered(draw, (cx, cy + 77), zone_label(snapshot.score), font(52, True), current_color)
    centered(draw, (cx, cy + 135), snapshot.rating.upper(), font(23), COLORS["subtle"])

    needle_angle = math.radians(angle(snapshot.score))
    draw.line((cx - math.cos(needle_angle) * 20, cy + math.sin(needle_angle) * 20, cx + math.cos(needle_angle) * 246, cy - math.sin(needle_angle) * 246), fill=COLORS["text"], width=10)
    draw.ellipse((cx - 15, cy - 15, cx + 15, cy + 15), fill=COLORS["text"])

    history_panel = (878, 128, 1566, 380)
    rounded(draw, history_panel, 26)
    draw.text((902, 152), "历史对比", font=font(27, True), fill=COLORS["text"])
    comparisons = [("上一交易日", snapshot.previous_close), ("一周前", snapshot.previous_1_week), ("一个月前", snapshot.previous_1_month)]
    for index, (label, value) in enumerate(comparisons):
        x = 902 + index * 216
        y = 198
        rounded(draw, (x, y, x + 198, y + 154), 20, "#FBFBFC")
        centered(draw, (x + 99, y + 28), label, font(19), COLORS["muted"])
        centered(draw, (x + 99, y + 76), format_score(value), font(42, True), zone_color(value))
        pill(draw, (x + 22, y + 108, x + 118, y + 140), zone_label(value), value)
        change = change_text(snapshot.score, value)
        change_color = COLORS["greed"] if change.startswith("↑") else COLORS["extreme fear"] if change.startswith("↓") else COLORS["subtle"]
        draw.text((x + 128, y + 114), change, font=font(18, True), fill=change_color)

    trend_panel = (878, 398, 1566, 744)
    rounded(draw, trend_panel, 26)
    draw.text((902, 422), "近30个交易日走势", font=font(27, True), fill=COLORS["text"])
    left, top, right, bottom = 940, 482, 1470, 689
    bands = [(0, 24, "extreme fear"), (25, 44, "fear"), (45, 55, "neutral"), (56, 75, "greed"), (76, 100, "extreme greed")]
    for low, high, key in bands:
        y1 = bottom - high / 100 * (bottom - top)
        y2 = bottom - low / 100 * (bottom - top)
        draw.rectangle((left, y1, right, y2), fill=COLORS[f"{key} fill"])
    for tick in (0, 25, 50, 75, 100):
        y = bottom - tick / 100 * (bottom - top)
        draw.line((left, y, right, y), fill="#D1D5DB", width=1)
        centered(draw, (left - 22, y), str(tick), font(14), COLORS["muted"])

    points = list(snapshot.history)
    if len(points) >= 2:
        coordinates: list[tuple[float, float]] = []
        for index, point in enumerate(points):
            x = left + index / (len(points) - 1) * (right - left)
            y = bottom - max(0, min(100, point.score)) / 100 * (bottom - top)
            coordinates.append((x, y))
        draw.line(coordinates, fill="#159447", width=4)
        for x, y in coordinates:
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="#FFFFFF", outline="#159447", width=2)
        x, y = coordinates[-1]
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill="#FFFFFF", outline="#159447", width=4)
        label_x = min(x - 10, right - 104)
        label_y = max(top + 8, y - 58)
        rounded(draw, (int(label_x), int(label_y), int(label_x + 100), int(label_y + 48)), 13, "#FFFFFF")
        centered(draw, (label_x + 50, label_y + 24), format_score(snapshot.score), font(23, True), current_color)

        label_count = min(6, len(points))
        for index in range(label_count):
            point_index = round(index * (len(points) - 1) / max(1, label_count - 1))
            point = points[point_index]
            x = left + point_index / (len(points) - 1) * (right - left)
            centered(draw, (x, bottom + 20), point.when.astimezone(BEIJING).strftime("%m-%d"), font(13), COLORS["muted"])
    else:
        centered(draw, ((left + right) / 2, (top + bottom) / 2), "历史数据暂不可用", font(18), COLORS["muted"])

    right_labels = [("极度贪婪", "76–100", "extreme greed"), ("贪婪", "56–75", "greed"), ("中性", "45–55", "neutral"), ("恐慌", "25–44", "fear"), ("极度恐慌", "0–24", "extreme fear")]
    y = 462
    for name, score_range, key in right_labels:
        draw.text((1490, y), name, font=font(15, True), fill=COLORS[key])
        draw.text((1490, y + 22), score_range, font=font(13), fill=COLORS["muted"])
        y += 52

    comment_panel = (34, 764, 1566, 854)
    rounded(draw, comment_panel, 22)
    draw.text((58, 787), "市场解读", font=font(26, True), fill=COLORS["text"])
    draw.text((58, 823), objective_comment(snapshot), font=font(23), fill=COLORS["muted"])
    draw.text((38, 872), "免责声明：本内容仅供参考，不构成任何投资建议。市场有风险，投资需谨慎。", font=font(14), fill=COLORS["subtle"])

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)
    return str(output)


def build_payload(snapshot: Snapshot) -> dict[str, Any]:
    caption = f"美股 Fear & Greed 每日播报｜{zone_label(snapshot.score)} {format_score(snapshot.score)}"
    if snapshot.previous_close is not None:
        caption += f"（较上一交易日 {change_text(snapshot.score, snapshot.previous_close)}）"
    return {"content": caption, "username": os.getenv("WEBHOOK_USERNAME", "市场情绪播报"), "allowed_mentions": {"parse": []}}


def multipart(payload: dict[str, Any], image_path: str) -> tuple[bytes, str]:
    boundary = f"----feargreed{uuid.uuid4().hex}"
    filename = Path(image_path).name
    mime = mimetypes.guess_type(filename)[0] or "image/png"
    pieces = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n\r\n{json.dumps(payload, ensure_ascii=False)}\r\n".encode("utf-8"),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"),
        Path(image_path).read_bytes(),
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(pieces), boundary


def post_webhook(url: str, payload: dict[str, Any], image_path: str) -> None:
    body, boundary = multipart(payload, image_path)
    request = Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "fear-greed-discord/3.0"}, method="POST")
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            if getattr(response, "status", 204) not in (200, 204):
                raise RuntimeError(f"Discord webhook returned HTTP {response.status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord webhook returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach Discord webhook: {exc.reason}") from exc


def main() -> int:
    dry_run = os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"}
    try:
        snapshot = parse_snapshot(fetch_json(os.getenv("FNG_API_URL", API_URL)))
        image_path = render_card(snapshot, os.getenv("OUTPUT_IMAGE_PATH", OUTPUT_PATH))
        payload = build_payload(snapshot)
        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print(f"Generated image: {image_path}")
            return 0
        webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if not webhook:
            raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
        post_webhook(webhook, payload, image_path)
        print(f"Broadcast sent: score={snapshot.score:.1f}, rating={snapshot.rating}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
