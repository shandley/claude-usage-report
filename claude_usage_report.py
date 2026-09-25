#!/usr/bin/env python3
"""Summarize your Claude Code usage from local session logs.

Reads token counts from ~/.claude/projects/**/*.jsonl. It reports only
numbers: no prompts, code, file contents, or project names leave your machine
unless you choose to share the output.

Usage:  python3 claude_usage_report.py [--days 30] [--name "Your Name"]

"API-equivalent cost" prices your tokens at Anthropic's public API list
prices (checked 2026-09-25). It is a yardstick for comparing people and
plans, not what your subscription charges you.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# $ per million tokens: (input, 5m cache write, 1h cache write, cache read, output).
# Keys are model IDs without the "claude-" prefix or a date suffix; matching is exact
# so that a new model shows up as unpriced instead of borrowing a relative's price.
PRICES: dict[str, tuple[float, float, float, float, float]] = {
    "fable-5-1": (10, 12.5, 20, 0.25, 50),
    "mythos-5-1": (10, 12.5, 20, 0.25, 50),
    "fable-5": (10, 12.5, 20, 1, 50),
    "mythos-5": (10, 12.5, 20, 1, 50),
    "opus-5-5": (4, 5, 8, 0.2, 20),
    "opus-5": (5, 6.25, 10, 0.5, 25),
    "opus-4-8": (5, 6.25, 10, 0.5, 25),
    "opus-4-7": (5, 6.25, 10, 0.5, 25),
    "opus-4-6": (5, 6.25, 10, 0.5, 25),
    "opus-4-5": (5, 6.25, 10, 0.5, 25),
    "opus-4-1": (15, 18.75, 30, 1.5, 75),
    "opus-4": (15, 18.75, 30, 1.5, 75),
    "sonnet-5": (2, 2.5, 4, 0.2, 10),
    "sonnet-4-6": (3, 3.75, 6, 0.3, 15),
    "sonnet-4-5": (3, 3.75, 6, 0.3, 15),
    "sonnet-4": (3, 3.75, 6, 0.3, 15),
    "haiku-4-5": (1, 1.25, 2, 0.1, 5),
    "haiku-3-5": (0.8, 1, 1.6, 0.08, 4),
}
FAST_MULTIPLIER = {
    "opus-5-5": 2.0,
    "opus-5": 2.0,
    "opus-4-8": 2.0,
}  # fast mode list prices
US_GEO_MULTIPLIER = 1.1  # inference_geo "us"
WEB_SEARCH_PER_REQUEST = 0.01  # $10 per 1,000 searches


def normalize(model: str) -> str:
    return re.sub(r"-\d{8}$", "", model.removeprefix("claude-"))


def tokens(u: dict) -> list[int]:
    """[input, 5m write, 1h write, cache read, output] for one usage block."""
    total_write = u.get("cache_creation_input_tokens", 0) or 0
    w1 = min(
        (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0) or 0,
        total_write,
    )
    return [
        u.get("input_tokens", 0) or 0,
        total_write - w1,
        w1,
        u.get("cache_read_input_tokens", 0) or 0,
        u.get("output_tokens", 0) or 0,
    ]


def parse(line: str) -> tuple[dict, datetime] | None:
    try:
        d = json.loads(line)
        if not isinstance(d, dict):
            return None
        t = datetime.fromisoformat(str(d["timestamp"]).replace("Z", "+00:00"))
        return (d, t) if t.tzinfo else None
    except (ValueError, TypeError, KeyError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--name", default="(not given)")
    args = ap.parse_args()

    today = (
        datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    )
    since = today - timedelta(
        days=args.days - 1
    )  # N full calendar days, including today
    root = Path.home() / ".claude" / "projects"
    requests: dict[str, tuple[datetime, str, dict]] = {}
    limit_hits: set[str] = set()  # rate-limit errors, de-duplicated to the minute
    sessions: set[str] = set()

    for f in root.rglob("*.jsonl"):
        try:
            if f.stat().st_mtime < since.timestamp():
                continue  # last written before the window, so it has no records in it
            fh = f.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"usage"' not in line and "rate_limit" not in line:
                    continue
                parsed = parse(line)
                if not parsed or parsed[1] < since:
                    continue
                d, t = parsed
                if d.get("error") == "rate_limit":
                    limit_hits.add(t.astimezone().strftime("%Y-%m-%dT%H:%M"))
                    continue
                msg = d.get("message")
                if not isinstance(msg, dict):
                    continue
                usage, model = msg.get("usage"), msg.get("model", "")
                if not isinstance(usage, dict) or not model or model == "<synthetic>":
                    continue
                # Streamed responses log the same request several times with growing
                # output counts; keep the most complete record.
                key = d.get("requestId") or msg.get("id") or f"{f}:{d['timestamp']}"
                prev = requests.get(key)
                if prev is None or (usage.get("output_tokens") or 0) >= (
                    prev[2].get("output_tokens") or 0
                ):
                    requests[key] = (t, model, usage)
                if d.get("sessionId"):
                    sessions.add(d["sessionId"])

    by_model: dict[str, list[float]] = defaultdict(
        lambda: [0.0] * 6
    )  # in, w5, w1, read, out, $
    by_week: dict[tuple[int, int], float] = defaultdict(float)
    active_days: set[str] = set()
    unpriced: set[str] = set()
    searches = 0
    for t, model, u in requests.values():
        # Each iteration (main turns, advisor calls, fallbacks) has its own tokens and
        # possibly its own model; the top-level totals leave some of them out.
        iterations = u.get("iterations") or [u]
        geo = US_GEO_MULTIPLIER if u.get("inference_geo") == "us" else 1.0
        cost = 0.0
        for it in iterations:
            if not isinstance(it, dict):
                continue
            m = normalize(it.get("model") or model)
            toks = tokens(it)
            p = PRICES.get(m)
            if p is None:
                unpriced.add(m)
            else:
                speed = FAST_MULTIPLIER.get(m, 1.0) if u.get("speed") == "fast" else 1.0
                c = sum(n * r for n, r in zip(toks, p)) / 1e6 * speed * geo
                cost += c
                by_model[m][5] += c
            for i, n in enumerate(toks):
                by_model[m][i] += n
        n_search = (u.get("server_tool_use") or {}).get("web_search_requests") or 0
        searches += n_search
        cost += n_search * WEB_SEARCH_PER_REQUEST
        local = t.astimezone()
        y, w, _ = local.isocalendar()
        by_week[(y, w)] += cost
        active_days.add(local.date().isoformat())

    search_cost = searches * WEB_SEARCH_PER_REQUEST
    total = sum(r[5] for r in by_model.values()) + search_cost
    M = 1e6
    print(f"Claude Code usage report: {args.name}")
    print(f"Window: last {args.days} days (generated {today:%Y-%m-%d})")
    print(
        f"Active days: {len(active_days)}   Sessions: {len(sessions)}   Requests: {len(requests)}"
    )
    print(f"Usage-limit hits: {len(limit_hits)}")
    print(
        f"API-equivalent cost: ${total:,.0f} total, ${total / max(args.days, 1) * 30:,.0f} per 30 days\n"
    )
    print(
        f"{'Model':<22}{'Input M':>9}{'Cache wr M':>11}{'Cache rd M':>11}{'Output M':>10}{'API $':>9}"
    )
    for m, r in sorted(by_model.items(), key=lambda kv: -kv[1][5]):
        print(
            f"{m[:22]:<22}{r[0] / M:>9.2f}{(r[1] + r[2]) / M:>11.2f}{r[3] / M:>11.1f}{r[4] / M:>10.2f}{r[5]:>9,.0f}"
        )
    if searches:
        print(f"{'web search':<22}{searches:>9,} searches{'':>32}{search_cost:>9,.0f}")
    first, current = since.isocalendar()[:2], today.isocalendar()[:2]
    print("\nAPI-equivalent $ by week:")
    for wk in sorted(by_week):
        partial = wk == current or (wk == first and since.weekday() != 0)
        note = "  (partial week)" if partial else ""
        print(f"  {wk[0]}-W{wk[1]:02d}  ${by_week[wk]:>8,.0f}{note}")
    if unpriced:
        print(
            f"\nModels without a list price (counted as $0): {', '.join(sorted(unpriced))}"
        )


if __name__ == "__main__":
    main()
