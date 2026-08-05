#!/usr/bin/env python3
"""Daily CNN Fear & Greed Index broadcaster for Discord.

No third-party dependencies are required. The script fetches CNN's public JSON
endpoint, creates a Chinese Discord embed, and posts it through a webhook.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
DEFAULT_TIMEOUT_SECONDS = 25
DEFAULT_RETRIES = 3

RATING_ZH = {
    "extreme fear": "极度恐慌",
    "fear": "恐慌",
    "neutral": "中性",
    "greed": "贪婪",
    "extreme greed": "极度贪婪",
}


@dataclass(frozen=True)
class Snapshot:
    score: float
    rating: str
    timestamp: str
    previous_close: float | None
    previous_1_week: float | None
    previous_1_month: float | None
    previous_1_year: float | None


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
    """Fetch JSON with browser-like headers and bounded retry behavior."""
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


def parse_snapshot(payload: dict[str, Any]) -> Snapshot:
    """Normalize CNN's current Fear & Greed response."""
    current = payload.get("fear_and_greed")
    if not isinstance(current, dict):
        raise ValueError("Missing 'fear_and_greed' object in API response")

    score = _number(current.get("score"))
    if score is None:
        raise ValueError("Missing or invalid Fear & Greed score")

    rating = str(current.get("rating") or classify_score(score)).strip().lower()
    timestamp = str(current.get("timestamp") or datetime.now(timezone.utc).isoformat())

    return Snapshot(
        score=score,
        rating=rating,
        timestamp=timestamp,
        previous_close=_number(current.get("previous_close")),
        previous_1_week=_number(current.get("previous_1_week")),
        previous_1_month=_number(current.get("previous_1_month")),
        previous_1_year=_number(current.get("previous_1_year")),
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
        base = "市场处于极度避险状态，情绪与波动风险均处于高位。"
    elif score <= 44:
        base = "市场情绪偏谨慎，资金风险偏好仍然不足。"
    elif score <= 55:
        base = "市场情绪接近中性，多空暂未形成明显压倒性优势。"
    elif score <= 74:
        base = "市场风险偏好较强，但需要留意追涨情绪继续升温。"
    else:
        base = "市场处于极度乐观状态，拥挤交易和回撤风险值得警惕。"

    if previous is None:
        trend = ""
    elif delta >= 8:
        trend = " 较上一交易日明显回暖。"
    elif delta >= 3:
        trend = " 较上一交易日继续改善。"
    elif delta <= -8:
        trend = " 较上一交易日快速降温。"
    elif delta <= -3:
        trend = " 较上一交易日有所走弱。"
    else:
        trend = " 较上一交易日变化不大。"

    return base + trend


def embed_color(score: float) -> int:
    if score <= 24:
        return 0xD93025
    if score <= 44:
        return 0xF57C00
    if score <= 55:
        return 0xFBC02D
    if score <= 74:
        return 0x43A047
    return 0x1B5E20


def build_discord_payload(snapshot: Snapshot) -> dict[str, Any]:
    rating_zh = RATING_ZH.get(snapshot.rating, snapshot.rating.title())
    title = os.getenv("BROADCAST_TITLE", "美股 Fear & Greed 每日播报")
    role_mention = os.getenv("DISCORD_ROLE_MENTION", "").strip()

    fields = [
        {
            "name": "上一交易日",
            "value": (
                f"{format_score(snapshot.previous_close)}  ·  "
                f"{change_text(snapshot.score, snapshot.previous_close)}"
            ),
            "inline": True,
        },
        {
            "name": "一周前",
            "value": (
                f"{format_score(snapshot.previous_1_week)}  ·  "
                f"{change_text(snapshot.score, snapshot.previous_1_week)}"
            ),
            "inline": True,
        },
        {
            "name": "一个月前",
            "value": (
                f"{format_score(snapshot.previous_1_month)}  ·  "
                f"{change_text(snapshot.score, snapshot.previous_1_month)}"
            ),
            "inline": True,
        },
        {
            "name": "市场解读",
            "value": market_commentary(snapshot),
            "inline": False,
        },
    ]

    description = (
        f"## {format_score(snapshot.score)} / 100\n"
        f"**当前状态：{rating_zh}**"
    )

    return {
        "username": os.getenv("WEBHOOK_USERNAME", "市场情绪播报"),
        "content": role_mention or None,
        "allowed_mentions": {"parse": ["roles"] if role_mention else []},
        "embeds": [
            {
                "title": f"📊 {title}",
                "description": description,
                "color": embed_color(snapshot.score),
                "fields": fields,
                "footer": {
                    "text": (
                        "数据来源：CNN Fear & Greed Index｜"
                        "仅供市场情绪参考，不构成投资建议"
                    )
                },
                "timestamp": normalize_timestamp(snapshot.timestamp),
            }
        ],
    }


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


def post_webhook(
    url: str,
    payload: dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "fear-greed-discord/1.0",
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

    try:
        raw = fetch_json(api_url)
        snapshot = parse_snapshot(raw)
        payload = build_discord_payload(snapshot)

        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if not webhook_url:
            raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")

        post_webhook(webhook_url, payload)
        print(f"Broadcast sent: score={snapshot.score:.1f}, rating={snapshot.rating}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
