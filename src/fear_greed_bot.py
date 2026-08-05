#!/usr/bin/env python3
"""Generate a visual CNN Fear & Greed card and publish it to Discord."""

from __future__ import annotations

import json
import math
import mimetypes
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

DEFAULT_API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
DEFAULT_TIMEOUT_SECONDS = 25
DEFAULT_RETRIES = 3
DEFAULT_IMAGE_PATH = "/tmp/fear-greed-card.png"

RATING_ZH = {
    "extreme fear": "极度恐慌",
    "fear": "恐慌",
    "neutral": "中性",
    "greed": "贪婪",
    "extreme greed": "极度贪婪",
}

RATING_EN = {
    "extreme fear": "EXTREME FEAR",
    "fear": "FEAR",
    "neutral": "NEUTRAL",
    "greed": "GREED",
    "extreme greed": "EXTREME GREED",
}

PALETTE = {
    "bg": "#070B14",
    "panel": "#101827",
    "panel_alt": "#131E30",
    "line": "#25324A",
    "text": "#F8FAFC",
    "muted": "#94A3B8",
    "subtle": "#64748B",
    "red": "#EF4444",
    "orange": "#F97316",
    "yellow": "#FACC15",
    "lime": "#84CC16",
    "green": "#22C55E",
    "blue": "#38BDF8",
}


@dataclass(frozen=True)
class HistoryPoint:
    timestamp: float
    score: float


@dataclass(frozen=True)
class Snapshot:
    score: float
    rating: str
    timestamp: str
    previous_close: float | None
    previous_1_week: float | None
    previous_1_month: float | None
    previous_1_year: float | None
    history: tuple[HistoryPoint, ...] = ()


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_json(
    url: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, Any]:
    """Fetch CNN JSON using browser-like headers and bounded retries."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers=headers, method="GET")
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Fear & Greed API returned a non-object JSON response")
            return data
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))

    raise RuntimeError(
        f"Unable to fetch Fear & Greed data after {retries} attempts: {last_error}"
    )


def _parse_history(payload: dict[str, Any]) -> tuple[HistoryPoint, ...]:
    historical = payload.get("fear_and_greed_historical")
    if not isinstance(historical, dict):
        return ()
    rows = historical.get("data")
    if not isinstance(rows, list):
        return ()

    points: list[HistoryPoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = _number(row.get("x"))
        score = _number(row.get("y"))
        if timestamp is None or score is None:
            continue
        points.append(HistoryPoint(timestamp=timestamp, score=max(0, min(100, score))))

    points.sort(key=lambda point: point.timestamp)
    return tuple(points[-30:])


def parse_snapshot(payload: dict[str, Any]) -> Snapshot:
    """Normalize CNN's current and historical Fear & Greed response."""
    current = payload.get("fear_and_greed")
    if not isinstance(current, dict):
        raise ValueError("Missing 'fear_and_greed' object in API response")

    score = _number(current.get("score"))
    if score is None:
        raise ValueError("Missing or invalid Fear & Greed score")

    rating = str(current.get("rating") or classify_score(score)).strip().lower()
    timestamp = str(current.get("timestamp") or datetime.now(timezone.utc).isoformat())

    return Snapshot(
        score=max(0, min(100, score)),
        rating=rating,
        timestamp=timestamp,
        previous_close=_number(current.get("previous_close")),
        previous_1_week=_number(current.get("previous_1_week")),
        previous_1_month=_number(current.get("previous_1_month")),
        previous_1_year=_number(current.get("previous_1_year")),
        history=_parse_history(payload),
    )


def classify_score(score: float) -> str:
    if score <= 24:
        return "extreme fear"
    if score <= 44:
        return "fear"
    if score <= 55:
        return "neutral"
    if score <= 74:
        return "greed"
    return "extreme greed"


def format_score(value: float | None) -> str:
    if value is None:
        return "暂无"
    rounded = round(value, 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"


def change_text(current: float, previous: float | None) -> str:
    if previous is None:
        return "暂无对比"
    delta = current - previous
    if abs(delta) < 0.05:
        return "→ 0.0"
    arrow = "↑" if delta > 0 else "↓"
    return f"{arrow} {abs(delta):.1f}"


def market_commentary(snapshot: Snapshot) -> str:
    score = snapshot.score
    previous = snapshot.previous_close
    delta = score - previous if previous is not None else 0

    if score <= 24:
        base = "市场处于极度避险状态，波动风险较高。"
    elif score <= 44:
        base = "市场情绪偏谨慎，资金风险偏好仍然不足。"
    elif score <= 55:
        base = "市场情绪接近中性，多空暂未形成明显优势。"
    elif score <= 74:
        base = "市场风险偏好较强，但需留意追涨情绪升温。"
    else:
        base = "市场处于极度乐观状态，拥挤交易和回撤风险上升。"

    if previous is None:
        trend = ""
    elif delta >= 8:
        trend = "较上一交易日明显回暖。"
    elif delta >= 3:
        trend = "较上一交易日继续改善。"
    elif delta <= -8:
        trend = "较上一交易日快速降温。"
    elif delta <= -3:
        trend = "较上一交易日有所走弱。"
    else:
        trend = "较上一交易日变化不大。"

    return f"{base}{trend}"


def score_color(score: float) -> str:
    if score <= 24:
        return PALETTE["red"]
    if score <= 44:
        return PALETTE["orange"]
    if score <= 55:
        return PALETTE["yellow"]
    if score <= 74:
        return PALETTE["lime"]
    return PALETTE["green"]


def embed_color(score: float) -> int:
    return int(score_color(score).lstrip("#"), 16)


def normalize_timestamp(value: str) -> str:
    """Return an ISO-8601 timestamp accepted by Discord."""
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()


def _display_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y.%m.%d")
    except ValueError:
        return datetime.now(timezone.utc).strftime("%Y.%m.%d")


def _font_path(bold: bool = False) -> str | None:
    env_name = "FONT_BOLD" if bold else "FONT_REGULAR"
    configured = os.getenv(env_name, "").strip()
    candidates = [configured] if configured else []
    if bold:
        candidates += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    return next((path for path in candidates if path and Path(path).exists()), None)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _font_path(bold)
    if path:
        return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _rounded_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int = 24,
    fill: str = PALETTE["panel"],
    outline: str | None = PALETTE["line"],
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if current and bbox[2] - bbox[0] > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _history_values(snapshot: Snapshot) -> list[float]:
    if snapshot.history:
        values = [point.score for point in snapshot.history]
        if abs(values[-1] - snapshot.score) > 0.05:
            values.append(snapshot.score)
        return values[-30:]
    fallback = [
        snapshot.previous_1_month,
        snapshot.previous_1_week,
        snapshot.previous_close,
        snapshot.score,
    ]
    return [float(value) for value in fallback if value is not None]


def render_card(snapshot: Snapshot, output_path: str = DEFAULT_IMAGE_PATH) -> str:
    """Render a 16:9 PNG market-sentiment card suitable for Discord."""
    width, height = 1200, 675
    image = Image.new("RGB", (width, height), PALETTE["bg"])
    draw = ImageDraw.Draw(image)

    title_font = _font(40, bold=True)
    kicker_font = _font(18, bold=True)
    label_font = _font(20, bold=True)
    small_font = _font(17)
    tiny_font = _font(14)
    score_font = _font(94, bold=True)
    status_font = _font(30, bold=True)
    compare_font = _font(32, bold=True)
    commentary_font = _font(20)

    accent = score_color(snapshot.score)
    rating_zh = RATING_ZH.get(snapshot.rating, snapshot.rating.title())
    rating_en = RATING_EN.get(snapshot.rating, snapshot.rating.upper())

    draw.text((54, 35), "MARKET SENTIMENT", font=kicker_font, fill=PALETTE["blue"])
    draw.text((54, 65), "美股 Fear & Greed 每日播报", font=title_font, fill=PALETTE["text"])
    date_text = _display_date(snapshot.timestamp)
    date_bbox = draw.textbbox((0, 0), date_text, font=small_font)
    draw.text(
        (1145 - (date_bbox[2] - date_bbox[0]), 47),
        date_text,
        font=small_font,
        fill=PALETTE["muted"],
    )
    draw.line((54, 122, 1146, 122), fill=PALETTE["line"], width=1)

    _rounded_panel(draw, (44, 145, 515, 590), radius=28)
    cx, cy, radius = 280, 385, 178
    segments = [
        (0, 24, PALETTE["red"]),
        (24, 44, PALETTE["orange"]),
        (44, 56, PALETTE["yellow"]),
        (56, 75, PALETTE["lime"]),
        (75, 100, PALETTE["green"]),
    ]
    arc_box = (cx - radius, cy - radius, cx + radius, cy + radius)
    for low, high, color in segments:
        start = 180 + low * 1.8
        end = 180 + high * 1.8
        draw.arc(arc_box, start=start, end=end, fill=color, width=30)

    marker_angle = math.radians(180 + snapshot.score * 1.8)
    mx = cx + math.cos(marker_angle) * radius
    my = cy + math.sin(marker_angle) * radius
    draw.ellipse(
        (mx - 10, my - 10, mx + 10, my + 10),
        fill=PALETTE["text"],
        outline=accent,
        width=4,
    )

    score_text = format_score(snapshot.score)
    score_bbox = draw.textbbox((0, 0), score_text, font=score_font)
    draw.text(
        (cx - (score_bbox[2] - score_bbox[0]) / 2, 285),
        score_text,
        font=score_font,
        fill=PALETTE["text"],
    )
    draw.text((cx + 86, 350), "/100", font=small_font, fill=PALETTE["muted"])

    status_bbox = draw.textbbox((0, 0), rating_zh, font=status_font)
    draw.text(
        (cx - (status_bbox[2] - status_bbox[0]) / 2, 417),
        rating_zh,
        font=status_font,
        fill=accent,
    )
    en_bbox = draw.textbbox((0, 0), rating_en, font=tiny_font)
    draw.text(
        (cx - (en_bbox[2] - en_bbox[0]) / 2, 462),
        rating_en,
        font=tiny_font,
        fill=PALETTE["subtle"],
    )

    comparison_items = [
        ("上一交易日", snapshot.previous_close),
        ("一周前", snapshot.previous_1_week),
        ("一个月前", snapshot.previous_1_month),
    ]
    x_positions = [545, 748, 951]
    for (label, value), x in zip(comparison_items, x_positions):
        _rounded_panel(
            draw,
            (x, 145, x + 182, 255),
            radius=20,
            fill=PALETTE["panel_alt"],
        )
        draw.text((x + 18, 163), label, font=small_font, fill=PALETTE["muted"])
        draw.text(
            (x + 18, 193),
            format_score(value),
            font=compare_font,
            fill=PALETTE["text"],
        )
        delta = change_text(snapshot.score, value)
        delta_color = PALETTE["muted"]
        if delta.startswith("↑"):
            delta_color = PALETTE["green"]
        elif delta.startswith("↓"):
            delta_color = PALETTE["red"]
        delta_bbox = draw.textbbox((0, 0), delta, font=small_font)
        draw.text(
            (x + 164 - (delta_bbox[2] - delta_bbox[0]), 205),
            delta,
            font=small_font,
            fill=delta_color,
        )

    chart_box = (545, 278, 1133, 455)
    _rounded_panel(draw, chart_box, radius=22, fill=PALETTE["panel_alt"])
    draw.text(
        (565, 295),
        "近30个交易日情绪趋势",
        font=label_font,
        fill=PALETTE["text"],
    )
    values = _history_values(snapshot)
    graph_left, graph_top, graph_right, graph_bottom = 567, 342, 1110, 426
    for score_line in (25, 50, 75):
        y = graph_bottom - (score_line / 100) * (graph_bottom - graph_top)
        draw.line((graph_left, y, graph_right, y), fill=PALETTE["line"], width=1)

    if len(values) >= 2:
        coords = []
        for index, value in enumerate(values):
            x = graph_left + (index / (len(values) - 1)) * (graph_right - graph_left)
            y = graph_bottom - (
                max(0, min(100, value)) / 100
            ) * (graph_bottom - graph_top)
            coords.append((x, y))
        draw.line(coords, fill=accent, width=4, joint="curve")
        for point in (coords[0], coords[-1]):
            draw.ellipse(
                (point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5),
                fill=PALETTE["text"],
                outline=accent,
                width=3,
            )
    else:
        draw.text(
            (graph_left, graph_top + 25),
            "历史数据暂不可用",
            font=small_font,
            fill=PALETTE["muted"],
        )

    draw.text((graph_left, 432), "30D AGO", font=tiny_font, fill=PALETTE["subtle"])
    today_bbox = draw.textbbox((0, 0), "TODAY", font=tiny_font)
    draw.text(
        (graph_right - (today_bbox[2] - today_bbox[0]), 432),
        "TODAY",
        font=tiny_font,
        fill=PALETTE["subtle"],
    )

    _rounded_panel(draw, (545, 478, 1133, 590), radius=22, fill=PALETTE["panel_alt"])
    draw.text((565, 497), "市场解读", font=label_font, fill=PALETTE["blue"])
    lines = _fit_text(draw, market_commentary(snapshot), commentary_font, 535)
    for line_no, line in enumerate(lines[:2]):
        draw.text(
            (565, 532 + line_no * 28),
            line,
            font=commentary_font,
            fill=PALETTE["text"],
        )

    draw.text(
        (54, 625),
        "DATA: CNN FEAR & GREED INDEX",
        font=tiny_font,
        fill=PALETTE["subtle"],
    )
    footer = "仅供市场情绪参考，不构成投资建议"
    footer_bbox = draw.textbbox((0, 0), footer, font=tiny_font)
    draw.text(
        (1146 - (footer_bbox[2] - footer_bbox[0]), 625),
        footer,
        font=tiny_font,
        fill=PALETTE["subtle"],
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def build_discord_payload(snapshot: Snapshot, with_image: bool = True) -> dict[str, Any]:
    rating_zh = RATING_ZH.get(snapshot.rating, snapshot.rating.title())
    title = os.getenv("BROADCAST_TITLE", "美股 Fear & Greed 每日播报")
    role_mention = os.getenv("DISCORD_ROLE_MENTION", "").strip()
    daily_change = change_text(snapshot.score, snapshot.previous_close)

    content_lines = []
    if role_mention:
        content_lines.append(role_mention)
    content_lines.append(
        f"**{title}｜{rating_zh} {format_score(snapshot.score)}**  "
        f"（较上一交易日 {daily_change}）"
    )

    embed: dict[str, Any] = {
        "description": market_commentary(snapshot),
        "color": embed_color(snapshot.score),
        "footer": {"text": "CNN Fear & Greed Index｜仅供参考，不构成投资建议"},
        "timestamp": normalize_timestamp(snapshot.timestamp),
    }
    if with_image:
        embed["image"] = {"url": "attachment://fear-greed-card.png"}

    return {
        "username": os.getenv("WEBHOOK_USERNAME", "市场情绪播报"),
        "content": "\n".join(content_lines),
        "allowed_mentions": {"parse": ["roles"] if role_mention else []},
        "embeds": [embed],
    }


def _multipart_body(payload: dict[str, Any], image_path: str) -> tuple[bytes, str]:
    boundary = f"----FearGreedBoundary{uuid.uuid4().hex}"
    image_name = "fear-greed-card.png"
    image_bytes = Path(image_path).read_bytes()
    content_type = mimetypes.guess_type(image_name)[0] or "application/octet-stream"

    chunks: list[bytes] = []

    def add(value: str | bytes) -> None:
        chunks.append(value.encode("utf-8") if isinstance(value, str) else value)

    add(f"--{boundary}\r\n")
    add('Content-Disposition: form-data; name="payload_json"\r\n')
    add("Content-Type: application/json; charset=utf-8\r\n\r\n")
    add(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    add("\r\n")

    add(f"--{boundary}\r\n")
    add(
        'Content-Disposition: form-data; name="files[0]"; '
        f'filename="{image_name}"\r\n'
    )
    add(f"Content-Type: {content_type}\r\n\r\n")
    add(image_bytes)
    add("\r\n")
    add(f"--{boundary}--\r\n")

    return b"".join(chunks), boundary


def post_webhook(
    url: str,
    payload: dict[str, Any],
    image_path: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    if image_path:
        body, boundary = _multipart_body(payload, image_path)
        content_type = f"multipart/form-data; boundary={boundary}"
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        content_type = "application/json"

    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": content_type,
            "User-Agent": "fear-greed-discord/2.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 204)
            if status not in (200, 204):
                raise RuntimeError(f"Discord webhook returned HTTP {status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Discord webhook returned HTTP {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach Discord webhook: {exc.reason}") from exc


def main() -> int:
    api_url = os.getenv("FNG_API_URL", DEFAULT_API_URL)
    dry_run = os.getenv("DRY_RUN", "").strip().lower() in {"1", "true", "yes"}
    image_path = os.getenv("OUTPUT_IMAGE_PATH", DEFAULT_IMAGE_PATH)

    try:
        raw = fetch_json(api_url)
        snapshot = parse_snapshot(raw)
        render_card(snapshot, image_path)
        payload = build_discord_payload(snapshot, with_image=True)

        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print(f"Preview image created: {image_path}")
            return 0

        webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if not webhook_url:
            raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")

        post_webhook(webhook_url, payload, image_path=image_path)
        print(
            f"Visual broadcast sent: score={snapshot.score:.1f}, "
            f"rating={snapshot.rating}, image={image_path}"
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
