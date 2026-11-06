#!/usr/bin/env python3
"""Generate a live CNN Fear & Greed dashboard and publish it to Discord."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageColor, ImageDraw, ImageFont

API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
OUTPUT_PATH = os.getenv("OUTPUT_IMAGE_PATH", "/tmp/fear-greed-card.png")
TIMEOUT = 25
RETRIES = 3
BEIJING = timezone(timedelta(hours=8))

# Dark card: it sits on Discord's dark theme, and only the score carries colour.
COLORS = {
    "bg": "#15171C",
    "text": "#F3F4F6",
    "muted": "#9CA3AF",
    "subtle": "#6B7280",
    "line": "#D1D5DB",
    "up": "#4ADE80",
    "down": "#F87171",
    "extreme fear": "#EF4444",
    "fear": "#F97316",
    "neutral": "#A1A1AA",
    "greed": "#4ADE80",
    "extreme greed": "#16A34A",
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


def objective_comment(snapshot: Snapshot) -> str:
    label = zone_label(snapshot.score)
    if snapshot.score >= 56:
        return f"市场情绪处于{label}区间，风险偏好较高。"
    if snapshot.score <= 44:
        return f"市场情绪处于{label}区间，风险偏好较低。"
    return "市场情绪处于中性区间，风险偏好相对均衡。"


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


ZONES = [(0, 24, "extreme fear"), (25, 44, "fear"), (45, 55, "neutral"), (56, 75, "greed"), (76, 100, "extreme greed")]


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


@lru_cache(maxsize=None)
def _face_index(path: str, bold: bool) -> int:
    """Pick the Simplified Chinese face of the wanted weight from a font collection."""
    styles = ("Bold", "Semibold") if bold else ("Regular",)
    for index in range(40):
        try:
            family, style = ImageFont.truetype(path, 12, index=index).getname()
        except OSError:
            break
        if "SC" in (family or "").split() and style in styles:
            return index
    return 0


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    path = _font_path(bold)
    if not path:
        return ImageFont.load_default(size)
    index = _face_index(path, bold) if path.endswith(".ttc") else 0
    return ImageFont.truetype(path, size, index=index)


def tint(color: str, amount: float) -> tuple[int, int, int]:
    """Blend a colour into the card background; amount 1 is the colour itself."""
    top, base = ImageColor.getrgb(color), ImageColor.getrgb(COLORS["bg"])
    return tuple(round(b + (t - b) * amount) for t, b in zip(top, base))  # type: ignore[return-value]


def text_width(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.ImageFont) -> float:
    return draw.textlength(text, font=text_font)


def change_color(change: str) -> str:
    return COLORS["up"] if change.startswith("↑") else COLORS["down"] if change.startswith("↓") else COLORS["muted"]


def render_card(snapshot: Snapshot, output_path: str = OUTPUT_PATH) -> str:
    """Draw a 1200x675 card that stays legible when Discord shrinks it to ~550px."""
    width, height = 1200, 675
    image = Image.new("RGB", (width, height), COLORS["bg"])
    draw = ImageDraw.Draw(image)
    left, column, right = 64, 620, 1136
    current = zone_color(snapshot.score)

    # Quiet header, so the score is the only loud element on the card.
    draw.text((left, 84), "美股恐贪指数", font=font(30, True), fill=COLORS["text"], anchor="ls")
    draw.text((left + text_width(draw, "美股恐贪指数", font(30, True)) + 16, 84), "CNN Fear & Greed", font=font(26), fill=COLORS["subtle"], anchor="ls")
    updated = snapshot.timestamp.astimezone(BEIJING).strftime("%m月%d日 %H:%M 北京时间")
    draw.text((right, 84), updated, font=font(26), fill=COLORS["muted"], anchor="rs")

    # Visual centre: score and zone.
    draw.text((left - 8, 318), format_score(snapshot.score), font=font(210, True), fill=current, anchor="ls")
    draw.text((left, 396), zone_label(snapshot.score), font=font(56, True), fill=current, anchor="ls")
    draw.text((left + text_width(draw, zone_label(snapshot.score), font(56, True)) + 18, 396), snapshot.rating.upper(), font=font(24), fill=COLORS["subtle"], anchor="ls")

    # Where the score sits on the 0-100 scale.
    bar_top, bar_height, gap = 440, 14, 6
    span = column - left
    for low, high, key in ZONES:
        x1 = left + low / 100 * span + (0 if low == 0 else gap / 2)
        x2 = left + min(high + 1, 100) / 100 * span - (0 if high == 100 else gap / 2)
        active = classify(snapshot.score) == key
        draw.rounded_rectangle((x1, bar_top, x2, bar_top + bar_height), radius=bar_height // 2, fill=COLORS[key] if active else tint(COLORS[key], 0.35))
    marker_x = left + max(0, min(100, snapshot.score)) / 100 * span
    marker_y = bar_top + bar_height / 2
    draw.ellipse((marker_x - 15, marker_y - 15, marker_x + 15, marker_y + 15), fill=COLORS["bg"])
    draw.ellipse((marker_x - 11, marker_y - 11, marker_x + 11, marker_y + 11), fill=COLORS["text"])
    draw.text((left, bar_top + 52), "极度恐慌", font=font(22), fill=COLORS["subtle"], anchor="ls")
    draw.text((column, bar_top + 52), "极度贪婪", font=font(22), fill=COLORS["subtle"], anchor="rs")

    # Secondary: change against earlier readings.
    comparisons = [("较前一交易日", snapshot.previous_close), ("较一周前", snapshot.previous_1_week)]
    for index, (label, value) in enumerate(comparisons):
        x = left + index * 290
        change = change_text(snapshot.score, value)
        draw.text((x, 566), label, font=font(24), fill=COLORS["muted"], anchor="ls")
        draw.text((x, 616), change, font=font(40, True), fill=change_color(change), anchor="ls")
        if value is not None:
            draw.text((x + text_width(draw, change, font(40, True)) + 14, 616), f"({format_score(value)})", font=font(24), fill=COLORS["subtle"], anchor="ls")

    # Context: the last 30 trading days, faint zone bands behind a neutral line.
    chart_left, chart_top, chart_right, chart_bottom = 700, 168, right, 560
    draw.text((chart_left, 140), "近 30 个交易日", font=font(24), fill=COLORS["muted"], anchor="ls")
    for low, high, key in ZONES:
        y1 = chart_bottom - min(high + 1, 100) / 100 * (chart_bottom - chart_top)
        y2 = chart_bottom - low / 100 * (chart_bottom - chart_top)
        draw.rectangle((chart_left, y1, chart_right, y2), fill=tint(COLORS[key], 0.12))
    for tick in (25, 50, 75):
        y = chart_bottom - tick / 100 * (chart_bottom - chart_top)
        draw.text((chart_right - 6, y - 6), str(tick), font=font(18), fill=COLORS["subtle"], anchor="rs")

    points = list(snapshot.history)
    if len(points) >= 2:
        coordinates = [
            (
                chart_left + index / (len(points) - 1) * (chart_right - chart_left - 48),
                chart_bottom - max(0, min(100, point.score)) / 100 * (chart_bottom - chart_top),
            )
            for index, point in enumerate(points)
        ]
        draw.line(coordinates, fill=COLORS["line"], width=4, joint="curve")
        x, y = coordinates[-1]
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=COLORS["bg"])
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=current)
        draw.text((chart_left, chart_bottom + 40), points[0].when.astimezone(BEIJING).strftime("%m-%d"), font=font(20), fill=COLORS["subtle"], anchor="ls")
        draw.text((x, chart_bottom + 40), points[-1].when.astimezone(BEIJING).strftime("%m-%d"), font=font(20), fill=COLORS["subtle"], anchor="ms")
    else:
        draw.text(((chart_left + chart_right) / 2, (chart_top + chart_bottom) / 2), "历史数据暂不可用", font=font(22), fill=COLORS["muted"], anchor="mm")

    draw.text((right, 640), "数据来源：CNN Business", font=font(20), fill=COLORS["subtle"], anchor="rs")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)
    return str(output)


def build_payload(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "content": f"今日落入‘{zone_label(snapshot.score)}’区间：{format_score(snapshot.score)}",
        "username": os.getenv("WEBHOOK_USERNAME", "市场情绪播报"),
        "allowed_mentions": {"parse": []},
    }


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
    request = Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "fear-greed-discord/4.1"},
        method="POST",
    )
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
        print(f"Broadcast sent: {snapshot.score:.1f} {snapshot.rating}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
