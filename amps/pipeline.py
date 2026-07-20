"""AMPS: オーケストレーター（状態機械）。

曲1本を planned → brief_done → lyrics_done → composed → prompted → qc_pending
まで進める advance()/run_full()、および週次（トレンド分析・自曲投稿インサイト・CEO企画）
をまとめて回す weekly_kickoff() を提供する。
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import config
import db
from agents import runner

GENRE_LABELS = {k: v["label"] for k, v in config.GENRES.items()}


# ------------------------------------------------------------ ファイル出力 ----

def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\-一-龠ぁ-んァ-ヶ]+", "_", text.strip())
    return text.strip("_") or "untitled"


def song_dir(song_id: int) -> Path:
    song = db.get_song(song_id)
    if song is None:
        raise ValueError(f"song not found: {song_id}")
    month = (song["week_of"] or datetime.now().strftime("%Y-%m-%d"))[:7]
    slug = _slugify(song["title"] or song["theme"] or "untitled")
    d = config.SONGS_DIR / month / f"{song_id:03d}_{slug}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(song_id: int, filename: str, content: str) -> None:
    (song_dir(song_id) / filename).write_text(content, encoding="utf-8")


# --------------------------------------------------------------- 補助抽出 ----

def _extract_field(text: str, label: str) -> Optional[str]:
    m = re.search(rf"{label}[：:]\s*([^\n]+)", text)
    return m.group(1).strip() if m else None


def _extract_score(text: str) -> Optional[int]:
    m = re.search(r"合計[：:]\s*(\d{1,3})\s*/\s*100", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,3})\s*/\s*100", text)
    return int(m.group(1)) if m else None


def _extract_bpm(text: str) -> Optional[int]:
    m = re.search(r"BPM[：:]\s*([0-9]{2,3})", text)
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ 曲単位 ----

def create_new_song(theme: str, genre: str, title: Optional[str] = None,
                     week_of: Optional[str] = None) -> int:
    if genre not in config.GENRES:
        raise ValueError(f"unknown genre: {genre} (expected one of {list(config.GENRES)})")
    week_of = week_of or date.today().isoformat()
    song_id = db.create_song(title=title or theme, genre=genre, theme=theme, week_of=week_of)
    return song_id


def _latest_qc_notes(song_id: int) -> str:
    reviews = db.list_reviews(song_id)
    return reviews[-1]["notes"] if reviews else ""


def advance(song_id: int) -> str:
    """現在のstatusを見て次の1エージェントを実行し、成果物を保存、statusを進める。実行後のstatusを返す。"""
    song = db.get_song(song_id)
    if song is None:
        raise ValueError(f"song not found: {song_id}")
    status = song["status"]

    if status == "planned":
        trend = db.get_latest_trend_report()
        post_insights = db.get_latest_post_insights()
        upstream = (
            f"仮タイトル：{song['title']}\nジャンル：{GENRE_LABELS.get(song['genre'], song['genre'])}\n"
            f"テーマ：{song['theme']}"
        )
        extra = ""
        if trend:
            extra += f"## トレンド分析（週次）\n{trend['content']}\n\n"
        if post_insights:
            extra += f"## 自曲投稿インサイト（週次）\n{post_insights['content']}\n"
        brief = runner.run_agent("music_director_agent", upstream, extra_context=extra, song_id=song_id)
        db.save_brief(song_id, brief)
        _write(song_id, "brief.md", brief)
        db.update_status(song_id, "brief_done")
        return "brief_done"

    if status == "brief_done":
        brief = db.get_brief(song_id)
        redo_notes = _latest_qc_notes(song_id)
        extra = f"## 差戻し・改善指示\n{redo_notes}" if redo_notes else ""
        lyrics = runner.run_agent("lyrics_agent", brief["content"], extra_context=extra, song_id=song_id)
        db.save_lyrics(song_id, lyrics, revision_notes=redo_notes)
        _write(song_id, "lyrics.md", lyrics)
        db.update_status(song_id, "lyrics_done")
        return "lyrics_done"

    if status == "lyrics_done":
        brief = db.get_brief(song_id)
        lyrics = db.get_latest_lyrics(song_id)
        upstream = f"{brief['content']}\n\n---\n{lyrics['content']}"
        composition = runner.run_agent("composition_agent", upstream, song_id=song_id)
        db.save_composition(song_id, bpm=_extract_bpm(composition),
                             key=_extract_field(composition, "Key"),
                             structure=_extract_field(composition, "構成"),
                             content=composition)
        _write(song_id, "composition.md", composition)
        db.update_status(song_id, "composed")
        return "composed"

    if status == "composed":
        composition = db.get_composition(song_id)
        lyrics = db.get_latest_lyrics(song_id)
        upstream = f"{composition['content']}\n\n---\n{lyrics['content']}"
        prompt = runner.run_agent("suno_prompt_agent", upstream, song_id=song_id)
        db.save_prompt(song_id, style_prompt=prompt, formatted_lyrics=lyrics["content"])
        _write(song_id, "suno_prompt.md", prompt)
        db.update_status(song_id, "prompted")
        return "prompted"

    if status == "prompted":
        lyrics = db.get_latest_lyrics(song_id)
        composition = db.get_composition(song_id)
        prompt = db.get_latest_prompt(song_id)
        upstream = f"{lyrics['content']}\n\n---\n{composition['content']}\n\n---\n{prompt['style_prompt']}"
        round_no = len(db.list_reviews(song_id)) + 1
        review = runner.run_agent("quality_check_agent", upstream,
                                   extra_context=f"Review {round_no}回目", song_id=song_id)
        score = _extract_score(review) or 0
        verdict = "pass" if score >= config.QC_PASS_SCORE else "redo"
        db.save_review(song_id, round_no, score, breakdown={"raw": review[:500]}, verdict=verdict, notes=review)
        _write(song_id, f"quality_review_round{round_no}.md", review)
        _write(song_id, "quality_review.md", review)
        db.update_quality_score(song_id, score)

        if verdict == "pass" or round_no >= config.QC_MAX_ROUNDS:
            db.update_status(song_id, "qc_pending")
            return "qc_pending"

        # 80点未満かつ再制作回数が残っている → Lyrics/Compositionを自動で再実行
        db.update_status(song_id, "brief_done")
        return "brief_done"

    return status


def run_full(song_id: int, max_steps: int = 20) -> str:
    """planned から qc_pending まで一気に流す。"""
    steps = 0
    status = db.get_song(song_id)["status"]
    while status != "qc_pending" and steps < max_steps:
        status = advance(song_id)
        steps += 1
    return status


def request_redo(song_id: int, comment: str) -> None:
    """人によるレビューキューでの差戻し。Lyrics/Compositionから再実行する。"""
    round_no = len(db.list_reviews(song_id)) + 1
    db.save_review(song_id, round_no, score=db.get_song(song_id)["quality_score"] or 0,
                    breakdown={"human_reject": True}, verdict="human_reject", notes=comment)
    db.update_status(song_id, "brief_done")


def approve(song_id: int) -> None:
    db.update_status(song_id, "qc_passed")


# ------------------------------------------------------------ 週次ワークフロー ----

def _format_posts_for_agent(since: str) -> str:
    db.recompute_viral_flags()
    posts = db.list_posts(limit=200)
    posts = [p for p in posts if p["posted_at"] >= since]
    if not posts:
        return "（対象期間の投稿データなし）"
    lines = ["| platform | posted_at | plays | likes | comments | shares | saves | viral | viral_score | content |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for p in posts:
        lines.append(
            f"| {p['platform']} | {p['posted_at']} | {p['plays']} | {p['likes']} | {p['comments']} | "
            f"{p['shares']} | {p['saves']} | {'YES' if p['is_viral'] else ''} | {p['viral_score']} | "
            f"{(p['content'] or '')[:80]} |"
        )
    return "\n".join(lines)


def weekly_kickoff(week_of: Optional[str] = None) -> dict:
    """毎週月曜に1回だけ実行する想定：Trend Analysis → Post Insights → CEO Agent の週次企画。"""
    week_of = week_of or date.today().isoformat()
    since = (date.fromisoformat(week_of) - timedelta(days=7)).isoformat()

    market_logs = db.list_market_research_since(since)
    market_text = "\n\n".join(row["content"] for row in market_logs) or "（直近1週間の市場調査ログなし）"
    trend_report = runner.run_agent("trend_analysis_agent", market_text)
    db.save_trend_report(week_of, trend_report)

    posts_text = _format_posts_for_agent(since)
    post_insights = runner.run_agent("post_insights_agent", posts_text)
    db.save_post_insights(week_of, post_insights)

    ceo_input = (
        f"# トレンド分析（週次・外部市場）\n{trend_report}\n\n"
        f"# 自曲投稿インサイト（週次・自ブランド実績）\n{post_insights}"
    )
    weekly_plan = runner.run_agent("ceo_agent", ceo_input)
    db.save_weekly_plan(week_of, weekly_plan)

    return {"week_of": week_of, "trend_report": trend_report,
            "post_insights": post_insights, "weekly_plan": weekly_plan}
