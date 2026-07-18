"""AMPS: 環境変数・パス・モデル名・ジャンル定数の集約。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AMPS_MODEL = os.getenv("AMPS_MODEL", "claude-sonnet-5")

# Suno連携（Phase2オプション。任意の第三者Suno APIプロバイダーを想定した汎用設定）
SUNO_API_KEY = os.getenv("SUNO_API_KEY", "")
SUNO_API_BASE_URL = os.getenv("SUNO_API_BASE_URL", "https://api.sunoapi.org")
SUNO_MODEL = os.getenv("SUNO_MODEL", "V4_5")

AGENTS_DIR = BASE_DIR / "agents"
BRAND_DIR = BASE_DIR / "brand"
SONGS_DIR = BASE_DIR / "songs"
REPORTS_DIR = BASE_DIR / "reports"
DATABASE_DIR = BASE_DIR / "database"
DB_PATH = BASE_DIR / "amps.db"
BRAND_GUIDELINE_PATH = BRAND_DIR / "brand_guideline.md"

# ジャンルと目標比率（合計100）
GENRES = {
    "love": {"label": "ラブソング", "target_ratio": 0.70},
    "cheer": {"label": "応援ソング", "target_ratio": 0.20},
    "vocaloid": {"label": "ボカロ系", "target_ratio": 0.10},
}

MONTHLY_SONG_TARGET = 30

# 品質評価の合格ライン／最大改稿回数
QC_PASS_SCORE = 80
QC_MAX_ROUNDS = 3

# 曲の状態遷移
SONG_STATUSES = [
    "planned",
    "brief_done",
    "lyrics_done",
    "composed",
    "prompted",
    "qc_pending",
    "qc_passed",
]

# パイプラインで実行するエージェント順（CEOは週次企画側で別管理のため任意）
PIPELINE_AGENT_ORDER = [
    "music_director_agent",
    "lyrics_agent",
    "composition_agent",
    "suno_prompt_agent",
    "quality_check_agent",
]

# 週次でのみ実行するエージェント（トレンド分析・自曲投稿インサイトは週1回、月曜想定）
WEEKLY_AGENTS = ["trend_analysis_agent", "post_insights_agent", "ceo_agent"]
WEEKLY_RUN_DAY = "mon"  # APSchedulerのday_of_week指定

# 日次で実行するエージェント（Phase1は簡易ログのみでも可）
DAILY_AGENTS = ["market_research_agent"]

# 「バズった」投稿の判定倍率（同プラットフォーム直近投稿平均の何倍で外れ値とみなすか）
VIRAL_THRESHOLD_MULTIPLIER = 2.0

# Suno音源生成の月間上限（課金プロバイダー側の設定に関わらず、ここで強制的に止める安全装置）。
# 月30曲リリース・改稿込みで最大50曲相当を想定し、余裕を持って150回/月をデフォルト上限にする。
# .envで SUNO_MONTHLY_GENERATION_CAP を設定すれば上書き可能。
SUNO_MONTHLY_GENERATION_CAP = int(os.getenv("SUNO_MONTHLY_GENERATION_CAP", "150"))


def ensure_dirs() -> None:
    for d in (SONGS_DIR, REPORTS_DIR, DATABASE_DIR):
        d.mkdir(parents=True, exist_ok=True)
