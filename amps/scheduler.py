"""AMPS: APScheduler設定。

- 日次：市場調査（Market Research Agent、簡易ログ）
- 週次（月曜）：Trend Analysis → Post Insights → CEO Agent の週次企画
  （トレンド分析・自曲投稿インサイトは週1回のみ実行。日次では回さない）

Phase 1では手動起動でも可のため、ダッシュボードのボタンからも同じ処理を呼べる
（pipeline.weekly_kickoff）。このファイルは常時起動プロセスとして自動化したい場合に使う。

起動: python scheduler.py
"""
from __future__ import annotations

from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import db
import pipeline
from agents import runner


def daily_market_research_job() -> None:
    """日次：市場調査ログ（Phase1は簡易ログのみ）。Trend Analysisはこれを週1回まとめて読む。"""
    today = date.today().isoformat()
    report = runner.run_agent(
        "market_research_agent",
        f"{today} 時点の対象ジャンル（ラブソング／応援ソング／ボカロ系）を中心とした市場傾向を、"
        "公開情報の一般的な傾向把握として要約してください。",
    )
    db.log_market_research(today, report)
    print(f"[scheduler] market research logged: {today}")


def weekly_kickoff_job() -> None:
    """週次（月曜）：Trend Analysis（週1回） → Post Insights（週1回） → CEO Agent。"""
    week_of = date.today().isoformat()
    result = pipeline.weekly_kickoff(week_of)
    print(f"[scheduler] weekly kickoff done for week_of={result['week_of']}")


def build_scheduler() -> BlockingScheduler:
    db.init_db()
    sched = BlockingScheduler(timezone="Asia/Tokyo")
    sched.add_job(daily_market_research_job, CronTrigger(hour=7, minute=0), id="daily_market_research")
    sched.add_job(
        weekly_kickoff_job,
        CronTrigger(day_of_week=config.WEEKLY_RUN_DAY, hour=8, minute=0),
        id="weekly_kickoff",
    )
    return sched


if __name__ == "__main__":
    scheduler = build_scheduler()
    print("AMPS scheduler started: daily market research (07:00 JST), "
          f"weekly trend/post-insights/CEO kickoff ({config.WEEKLY_RUN_DAY} 08:00 JST). Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
