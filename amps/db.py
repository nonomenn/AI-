"""AMPS: SQLite初期化とCRUDヘルパー。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Optional

import config

DDL = """
CREATE TABLE IF NOT EXISTS songs (
  song_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  title       TEXT,
  genre       TEXT,           -- love / cheer / vocaloid
  theme       TEXT,
  status      TEXT NOT NULL,
  quality_score INTEGER,
  week_of     TEXT,           -- 例 2026-07-13
  created_at  TEXT DEFAULT (datetime('now')),
  updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS briefs (
  song_id INTEGER PRIMARY KEY,
  content TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE IF NOT EXISTS lyrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER,
  version INTEGER,
  content TEXT,
  revision_notes TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE IF NOT EXISTS compositions (
  song_id INTEGER PRIMARY KEY,
  bpm INTEGER, key TEXT, structure TEXT, content TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE IF NOT EXISTS suno_prompts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER, version INTEGER,
  style_prompt TEXT, formatted_lyrics TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE IF NOT EXISTS quality_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER, round INTEGER,
  score INTEGER, breakdown_json TEXT,
  verdict TEXT,     -- pass / redo
  notes TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER, agent TEXT,
  input_summary TEXT, output_summary TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- 自ブランドのSNS投稿実績（Post Insights Agentの入力）
CREATE TABLE IF NOT EXISTS posts (
  post_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id     INTEGER,          -- 紐づく曲。ブランド全般の投稿ならNULL可
  platform    TEXT NOT NULL,    -- x / instagram / tiktok / youtube_shorts 等
  content     TEXT,             -- 投稿文・使用フレーズのメモ
  posted_at   TEXT NOT NULL,    -- 例 2026-07-13
  plays       INTEGER DEFAULT 0,
  likes       INTEGER DEFAULT 0,
  comments    INTEGER DEFAULT 0,
  shares      INTEGER DEFAULT 0,
  saves       INTEGER DEFAULT 0,
  is_viral    INTEGER DEFAULT 0,   -- 集計時に自動判定（0/1）
  viral_score REAL,                -- 直近平均に対する倍率
  created_at  TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

-- Post Insights Agent の週次レポート
CREATE TABLE IF NOT EXISTS post_insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  week_of TEXT NOT NULL,
  content TEXT,              -- Post Insights Agentの出力（Markdown）
  created_at TEXT DEFAULT (datetime('now'))
);

-- Trend Analysis Agent の週次レポート
CREATE TABLE IF NOT EXISTS trend_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  week_of TEXT NOT NULL,
  content TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- 日次市場調査ログ（Phase1は簡易ログのみ）
CREATE TABLE IF NOT EXISTS market_research_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_date TEXT NOT NULL,
  content TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- CEO Agent の週次制作リスト
CREATE TABLE IF NOT EXISTS weekly_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  week_of TEXT NOT NULL,
  content TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    config.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(DDL)


# ---------------------------------------------------------------- songs ----

def create_song(title: str, genre: str, theme: str, week_of: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO songs (title, genre, theme, status, week_of) VALUES (?, ?, ?, 'planned', ?)",
            (title, genre, theme, week_of),
        )
        return cur.lastrowid


def update_status(song_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE songs SET status = ?, updated_at = datetime('now') WHERE song_id = ?",
            (status, song_id),
        )


def update_quality_score(song_id: int, score: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE songs SET quality_score = ?, updated_at = datetime('now') WHERE song_id = ?",
            (score, song_id),
        )


def get_song(song_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM songs WHERE song_id = ?", (song_id,)).fetchone()


def list_songs(week_of: Optional[str] = None) -> list[sqlite3.Row]:
    with get_conn() as conn:
        if week_of:
            return conn.execute(
                "SELECT * FROM songs WHERE week_of = ? ORDER BY song_id DESC", (week_of,)
            ).fetchall()
        return conn.execute("SELECT * FROM songs ORDER BY song_id DESC").fetchall()


def list_by_status(status: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM songs WHERE status = ? ORDER BY song_id DESC", (status,)
        ).fetchall()


# --------------------------------------------------------------- briefs ----

def save_brief(song_id: int, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO briefs (song_id, content) VALUES (?, ?) "
            "ON CONFLICT(song_id) DO UPDATE SET content = excluded.content, created_at = datetime('now')",
            (song_id, content),
        )


def get_brief(song_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM briefs WHERE song_id = ?", (song_id,)).fetchone()


# --------------------------------------------------------------- lyrics ----

def save_lyrics(song_id: int, content: str, revision_notes: str = "") -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM lyrics WHERE song_id = ?", (song_id,)
        ).fetchone()
        version = row["v"] + 1
        cur = conn.execute(
            "INSERT INTO lyrics (song_id, version, content, revision_notes) VALUES (?, ?, ?, ?)",
            (song_id, version, content, revision_notes),
        )
        return cur.lastrowid


def list_lyrics(song_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM lyrics WHERE song_id = ? ORDER BY version ASC", (song_id,)
        ).fetchall()


def get_latest_lyrics(song_id: int) -> Optional[sqlite3.Row]:
    rows = list_lyrics(song_id)
    return rows[-1] if rows else None


# --------------------------------------------------------- compositions ----

def save_composition(song_id: int, bpm: Optional[int], key: Optional[str],
                      structure: Optional[str], content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO compositions (song_id, bpm, key, structure, content) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(song_id) DO UPDATE SET bpm=excluded.bpm, key=excluded.key, "
            "structure=excluded.structure, content=excluded.content, created_at=datetime('now')",
            (song_id, bpm, key, structure, content),
        )


def get_composition(song_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM compositions WHERE song_id = ?", (song_id,)).fetchone()


# ----------------------------------------------------------- suno_prompt ----

def save_prompt(song_id: int, style_prompt: str, formatted_lyrics: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM suno_prompts WHERE song_id = ?", (song_id,)
        ).fetchone()
        version = row["v"] + 1
        cur = conn.execute(
            "INSERT INTO suno_prompts (song_id, version, style_prompt, formatted_lyrics) VALUES (?, ?, ?, ?)",
            (song_id, version, style_prompt, formatted_lyrics),
        )
        return cur.lastrowid


def get_latest_prompt(song_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM suno_prompts WHERE song_id = ? ORDER BY version DESC LIMIT 1", (song_id,)
        ).fetchone()


# ------------------------------------------------------- quality_reviews ----

def save_review(song_id: int, round_no: int, score: int, breakdown: Any,
                 verdict: str, notes: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO quality_reviews (song_id, round, score, breakdown_json, verdict, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (song_id, round_no, score, json.dumps(breakdown, ensure_ascii=False), verdict, notes),
        )


def list_reviews(song_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM quality_reviews WHERE song_id = ? ORDER BY round ASC", (song_id,)
        ).fetchall()


# ------------------------------------------------------------ agent_runs ----

def log_agent_run(song_id: Optional[int], agent: str, input_summary: str, output_summary: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_runs (song_id, agent, input_summary, output_summary) VALUES (?, ?, ?, ?)",
            (song_id, agent, input_summary[:2000], output_summary[:2000]),
        )


# ------------------------------------------------------------------ posts ----

def add_post(platform: str, content: str, posted_at: str, plays: int = 0, likes: int = 0,
             comments: int = 0, shares: int = 0, saves: int = 0,
             song_id: Optional[int] = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO posts (song_id, platform, content, posted_at, plays, likes, comments, shares, saves) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (song_id, platform, content, posted_at, plays, likes, comments, shares, saves),
        )
        return cur.lastrowid


def list_posts(limit: int = 200) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM posts ORDER BY posted_at DESC LIMIT ?", (limit,)
        ).fetchall()


def _post_primary_metric(row: sqlite3.Row) -> int:
    # 再生数があれば再生数、なければいいね数を主指標にする
    return row["plays"] if row["plays"] else row["likes"]


def recompute_viral_flags(multiplier: float = None) -> list[dict]:
    """プラットフォームごとに直近投稿の平均と比較し、外れ値をバズ判定してDBへ反映する。"""
    multiplier = multiplier or config.VIRAL_THRESHOLD_MULTIPLIER
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM posts").fetchall()
        by_platform: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            by_platform.setdefault(r["platform"], []).append(r)

        results = []
        for platform, prows in by_platform.items():
            metrics = [_post_primary_metric(r) for r in prows]
            avg = sum(metrics) / len(metrics) if metrics else 0
            for r in prows:
                metric = _post_primary_metric(r)
                score = (metric / avg) if avg > 0 else 0.0
                is_viral = 1 if (avg > 0 and metric >= avg * multiplier) else 0
                conn.execute(
                    "UPDATE posts SET is_viral = ?, viral_score = ? WHERE post_id = ?",
                    (is_viral, round(score, 2), r["post_id"]),
                )
                results.append(
                    {"post_id": r["post_id"], "platform": platform, "is_viral": bool(is_viral), "viral_score": round(score, 2)}
                )
        return results


def list_viral_posts(since: Optional[str] = None) -> list[sqlite3.Row]:
    with get_conn() as conn:
        if since:
            return conn.execute(
                "SELECT * FROM posts WHERE is_viral = 1 AND posted_at >= ? ORDER BY viral_score DESC",
                (since,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM posts WHERE is_viral = 1 ORDER BY viral_score DESC"
        ).fetchall()


# ------------------------------------------------------------ post_insights ----

def save_post_insights(week_of: str, content: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO post_insights (week_of, content) VALUES (?, ?)", (week_of, content)
        )
        return cur.lastrowid


def get_latest_post_insights() -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM post_insights ORDER BY id DESC LIMIT 1"
        ).fetchone()


# ------------------------------------------------------------ trend_reports ----

def save_trend_report(week_of: str, content: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO trend_reports (week_of, content) VALUES (?, ?)", (week_of, content)
        )
        return cur.lastrowid


def get_latest_trend_report() -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM trend_reports ORDER BY id DESC LIMIT 1"
        ).fetchone()


# ------------------------------------------------------ market_research_logs ----

def log_market_research(log_date: str, content: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO market_research_logs (log_date, content) VALUES (?, ?)",
            (log_date, content),
        )
        return cur.lastrowid


def list_market_research_since(since: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM market_research_logs WHERE log_date >= ? ORDER BY log_date ASC",
            (since,),
        ).fetchall()


# ------------------------------------------------------------- weekly_plans ----

def save_weekly_plan(week_of: str, content: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO weekly_plans (week_of, content) VALUES (?, ?)", (week_of, content)
        )
        return cur.lastrowid


def get_latest_weekly_plan() -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM weekly_plans ORDER BY id DESC LIMIT 1"
        ).fetchone()


if __name__ == "__main__":
    init_db()
    print(f"initialized: {config.DB_PATH}")
