"""
Personality trajectory tests (Track C — partials plan).

The trajectory endpoint reads the REAL snapshot table the live personality
system writes (`personality_snapshots_v2`) and aggregates its traits onto the
three personality axes. These tests seed that table with rows (ordinary test
fixtures — the production path never fabricates data) and assert the endpoint's
honest behaviour: empty for an unseen user, chronological, limit-aware, and
computing axis means from real values only.

Run: python -m pytest server/tests/test_personality_trajectory.py -v
"""

import asyncio
import json

import pytest

from server.db import get_db_connection
from server.routers.analytics import (
    _axis_means,
    get_personality_trajectory,
)


def _seed(user_id: str, snapshots):
    """Insert real rows into the v2 snapshot table the endpoint reads."""
    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS personality_snapshots_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                traits_json TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        for ts, traits in snapshots:
            conn.execute(
                "INSERT INTO personality_snapshots_v2 (user_id, traits_json, timestamp)"
                " VALUES (?, ?, ?)",
                (user_id, json.dumps(traits), ts),
            )
        conn.commit()
    finally:
        conn.close()


def test_trajectory_empty_for_unknown_user(isolated_db):
    result = asyncio.run(get_personality_trajectory(user_id="nobody"))
    assert result["points"] == []
    assert result["count"] == 0
    # the core baseline is always present as the reference origin
    assert set(result["core"]) == {"cognitive", "emotional", "social"}


def test_trajectory_returns_chronological_points(isolated_db):
    base = 1_700_000_000.0
    _seed("alice", [
        (base + 300, {"cognitive.curiosity": 0.8, "emotional.warmth": 0.7, "social.openness": 0.6}),
        (base + 100, {"cognitive.curiosity": 0.6, "emotional.warmth": 0.5, "social.openness": 0.4}),
        (base + 200, {"cognitive.curiosity": 0.7, "emotional.warmth": 0.6, "social.openness": 0.5}),
    ])

    result = asyncio.run(get_personality_trajectory(user_id="alice"))
    assert result["count"] == 3

    # points come back oldest → newest regardless of insert order
    ts = [p["ts"] for p in result["points"]]
    assert ts == sorted(ts)

    first = result["points"][0]
    assert first["cognitive"] == pytest.approx(0.6)
    assert first["emotional"] == pytest.approx(0.5)
    assert first["social"] == pytest.approx(0.4)


def test_trajectory_limit_keeps_newest_and_stays_chronological(isolated_db):
    base = 1_700_000_000.0
    _seed("bob", [(base + i, {"cognitive.curiosity": 0.1 * i}) for i in range(10)])

    result = asyncio.run(get_personality_trajectory(user_id="bob", limit=3))
    assert result["count"] == 3

    vals = [p["traits"]["cognitive.curiosity"] for p in result["points"]]
    assert vals == pytest.approx([0.7, 0.8, 0.9])


def test_axis_means_ignores_non_numeric_and_bools():
    out = _axis_means({
        "cognitive.curiosity": 0.5,
        "cognitive.depth": True,          # bool excluded
        "emotional.warmth": "x",          # non-numeric excluded
        "noaxis": 0.9,                    # not an axis.trait key
    })
    assert out == {"cognitive": 0.5}
