"""AMPS: Streamlitダッシュボード（人の操作卓）。

起動: streamlit run dashboard.py
"""
from __future__ import annotations

from datetime import date

import streamlit as st

import config
import db
import pipeline
from connectors import suno

st.set_page_config(page_title="AMPS — AI Music Production System", layout="wide")
db.init_db()

GENRE_LABELS = {k: v["label"] for k, v in config.GENRES.items()}

PAGES = ["ホーム", "新規企画", "レビューキュー", "自分の投稿分析", "曲詳細"]
page = st.sidebar.radio("メニュー", PAGES)
st.sidebar.markdown("---")
st.sidebar.caption(
    "トレンド分析・自曲投稿インサイトは週1回（月曜）実行が基本です。"
    "手動で今すぐ回したい場合は下のボタンから。"
)
if st.sidebar.button("週次企画を今すぐ実行（Trend→PostInsights→CEO）"):
    with st.spinner("Trend Analysis → Post Insights → CEO Agent を実行中..."):
        try:
            result = pipeline.weekly_kickoff(date.today().isoformat())
            st.sidebar.success(f"{result['week_of']} 週の企画を更新しました。")
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"失敗しました: {exc}")

if config.SUNO_API_KEY:
    st.sidebar.caption(
        f"Suno音源生成：残り {suno.remaining_quota()} / {config.SUNO_MONTHLY_GENERATION_CAP} 回（今月）"
    )
else:
    st.sidebar.caption("Suno音源生成：未設定（.envにSUNO_API_KEYを設定すると使えます）")


def genre_ratio_chart(songs) -> None:
    counts = {g: 0 for g in config.GENRES}
    for s in songs:
        if s["genre"] in counts:
            counts[s["genre"]] += 1
    total = sum(counts.values()) or 1
    cols = st.columns(len(config.GENRES))
    for col, (genre, meta) in zip(cols, config.GENRES.items()):
        actual = counts[genre] / total
        with col:
            st.metric(
                meta["label"],
                f"{counts[genre]}曲 ({actual:.0%})",
                delta=f"目標 {meta['target_ratio']:.0%}",
            )


# ------------------------------------------------------------------ ホーム ----
if page == "ホーム":
    st.title("AMPS ホーム")
    week_of = date.today().isoformat()
    songs = db.list_songs()

    st.subheader("ジャンル比率（全曲・目標との対比）")
    genre_ratio_chart(songs)

    st.subheader("最新の週次制作リスト")
    plan = db.get_latest_weekly_plan()
    if plan:
        st.caption(f"週：{plan['week_of']}")
        st.markdown(plan["content"])
    else:
        st.info("週次企画がまだ実行されていません。サイドバーの「週次企画を今すぐ実行」から開始してください。")

    st.subheader("曲一覧")
    if not songs:
        st.info("まだ曲がありません。「新規企画」から作成してください。")
    for s in songs:
        with st.expander(f"[{s['status']}] {s['title']}（{GENRE_LABELS.get(s['genre'], s['genre'])}） "
                          f"QC: {s['quality_score'] if s['quality_score'] is not None else '-'}点"):
            st.write(f"テーマ：{s['theme']}")
            st.write(f"週：{s['week_of']}")

# ---------------------------------------------------------------- 新規企画 ----
elif page == "新規企画":
    st.title("新規企画")
    with st.form("new_song_form"):
        theme = st.text_input("テーマ", placeholder="例：帰り道")
        genre_key = st.selectbox("ジャンル", list(config.GENRES.keys()),
                                  format_func=lambda k: GENRE_LABELS[k])
        title = st.text_input("仮タイトル（未入力ならテーマを使用）")
        submitted = st.form_submit_button("制作開始（企画→歌詞→設計→Sunoプロンプト→品質評価）")

    if submitted:
        if not theme:
            st.error("テーマを入力してください。")
        else:
            song_id = pipeline.create_new_song(theme=theme, genre=genre_key, title=title or None)
            with st.spinner("Music Director → Lyrics → Composition → Suno Prompt → Quality Check を実行中..."):
                try:
                    final_status = pipeline.run_full(song_id)
                    st.success(f"song_id={song_id} が status={final_status} まで進みました。")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"パイプライン実行中にエラー: {exc}")

# -------------------------------------------------------------- レビューキュー ----
elif page == "レビューキュー":
    st.title("レビューキュー（品質評価後・要承認）")
    pending = db.list_by_status("qc_pending")
    if not pending:
        st.info("承認待ちの曲はありません。")
    for s in pending:
        st.markdown(f"## {s['title']}（{GENRE_LABELS.get(s['genre'], s['genre'])}） — QCスコア: {s['quality_score']}")
        lyrics = db.get_latest_lyrics(s["song_id"])
        prompt = db.get_latest_prompt(s["song_id"])
        reviews = db.list_reviews(s["song_id"])

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 歌詞")
            st.markdown(lyrics["content"] if lyrics else "（未生成）")
        with col2:
            st.markdown("### Sunoプロンプト（コピー用）")
            st.code(prompt["style_prompt"] if prompt else "（未生成）", language="text")

        st.markdown("### 品質評価履歴")
        for r in reviews:
            st.markdown(f"**Round {r['round']}：{r['score']}点（{r['verdict']}）**")
            with st.expander("詳細を見る"):
                st.markdown(r["notes"])

        st.markdown("### Suno音源生成")
        if not config.SUNO_API_KEY:
            st.caption("未設定：.envにSUNO_API_KEYを設定すると、ここから音源を自動生成できます。")
        else:
            gens = db.list_suno_generations(s["song_id"])
            for g in gens:
                if g["status"] == "done" and g["audio_local_path"]:
                    st.audio(g["audio_local_path"])
                elif g["status"] == "failed":
                    st.caption(f"生成失敗：{g['error']}")
            if st.button(f"Sunoで音源生成する（残り{suno.remaining_quota()}回/月）",
                         key=f"suno_gen_{s['song_id']}"):
                with st.spinner("Suno APIで音源を生成中（数分かかることがあります）..."):
                    try:
                        result = suno.generate_song(
                            s["song_id"], prompt["style_prompt"], prompt["formatted_lyrics"], s["title"]
                        )
                        st.success(f"音源を生成しました：{result['audio_local_path']}")
                        st.rerun()
                    except suno.SunoQuotaExceeded as exc:
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"生成に失敗しました：{exc}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("承認する", key=f"approve_{s['song_id']}"):
                pipeline.approve(s["song_id"])
                st.success("承認しました（qc_passed）。")
                st.rerun()
        with c2:
            comment = st.text_input("差戻しコメント", key=f"comment_{s['song_id']}")
            if st.button("差戻し（再制作）", key=f"reject_{s['song_id']}"):
                pipeline.request_redo(s["song_id"], comment)
                with st.spinner("Lyrics/Compositionを再実行中..."):
                    pipeline.run_full(s["song_id"])
                st.success("差戻し、再制作しました。")
                st.rerun()
        st.markdown("---")

# ------------------------------------------------------------ 自分の投稿分析 ----
elif page == "自分の投稿分析":
    st.title("自分の投稿分析（バズった投稿 → 次回の曲作りへ）")
    st.caption(
        "自分（自ブランド）のSNS投稿の実績を記録すると、Post Insights Agentが週1回、"
        "バズった投稿とその理由を分析し、次回のMusic Director Agentのブリーフに反映します。"
    )

    with st.form("new_post_form"):
        songs = db.list_songs()
        song_options = {0: "（曲に紐づけない／ブランド全般の投稿）"}
        song_options.update({s["song_id"]: s["title"] for s in songs})
        col1, col2, col3 = st.columns(3)
        with col1:
            platform = st.selectbox("プラットフォーム", ["x", "instagram", "tiktok", "youtube_shorts"])
            posted_at = st.date_input("投稿日", value=date.today())
        with col2:
            song_id_choice = st.selectbox("紐づく曲", list(song_options.keys()),
                                           format_func=lambda k: song_options[k])
            plays = st.number_input("再生数", min_value=0, value=0)
        with col3:
            likes = st.number_input("いいね数", min_value=0, value=0)
            comments = st.number_input("コメント数", min_value=0, value=0)
        shares = st.number_input("シェア数", min_value=0, value=0)
        saves = st.number_input("保存数", min_value=0, value=0)
        content = st.text_area("投稿文・使用フレーズのメモ")
        post_submitted = st.form_submit_button("投稿実績を記録")

    if post_submitted:
        db.add_post(
            platform=platform, content=content, posted_at=posted_at.isoformat(),
            plays=int(plays), likes=int(likes), comments=int(comments),
            shares=int(shares), saves=int(saves),
            song_id=song_id_choice or None,
        )
        st.success("投稿実績を記録しました。")
        st.rerun()

    st.subheader("投稿実績一覧（バズ判定込み）")
    db.recompute_viral_flags()
    posts = db.list_posts()
    if not posts:
        st.info("まだ投稿データがありません。上のフォームから記録してください。")
    else:
        st.dataframe(
            [{
                "投稿日": p["posted_at"], "プラットフォーム": p["platform"],
                "再生": p["plays"], "いいね": p["likes"], "コメント": p["comments"],
                "シェア": p["shares"], "保存": p["saves"],
                "バズ判定": "🔥 バズった" if p["is_viral"] else "",
                "平均比": p["viral_score"], "メモ": p["content"],
            } for p in posts],
            use_container_width=True,
        )

    st.subheader("最新の自曲投稿インサイト（週次）")
    insights = db.get_latest_post_insights()
    if insights:
        st.caption(f"週：{insights['week_of']}")
        st.markdown(insights["content"])
    else:
        st.info("まだ生成されていません。サイドバーの「週次企画を今すぐ実行」から生成できます。")

# ---------------------------------------------------------------- 曲詳細 ----
elif page == "曲詳細":
    st.title("曲詳細")
    songs = db.list_songs()
    if not songs:
        st.info("まだ曲がありません。")
    else:
        options = {s["song_id"]: f"{s['title']}（{s['status']}）" for s in songs}
        song_id = st.selectbox("曲を選択", list(options.keys()), format_func=lambda k: options[k])
        song = db.get_song(song_id)

        st.subheader(f"{song['title']} — status: {song['status']}")

        brief = db.get_brief(song_id)
        if brief:
            with st.expander("ブリーフ（brief.md）", expanded=True):
                st.markdown(brief["content"])

        lyrics_versions = db.list_lyrics(song_id)
        if lyrics_versions:
            with st.expander(f"歌詞（全{len(lyrics_versions)}版）"):
                for lv in lyrics_versions:
                    st.markdown(f"#### version {lv['version']}")
                    st.markdown(lv["content"])
                    st.markdown("---")

        composition = db.get_composition(song_id)
        if composition:
            with st.expander("楽曲設計（composition.md）"):
                st.markdown(composition["content"])

        prompt = db.get_latest_prompt(song_id)
        if prompt:
            with st.expander("Sunoプロンプト"):
                st.code(prompt["style_prompt"], language="text")

        reviews = db.list_reviews(song_id)
        if reviews:
            with st.expander(f"品質評価履歴（全{len(reviews)}回）"):
                for r in reviews:
                    st.markdown(f"**Round {r['round']}：{r['score']}点（{r['verdict']}）**")
                    st.markdown(r["notes"])
                    st.markdown("---")

        gens = db.list_suno_generations(song_id)
        done_gens = [g for g in gens if g["status"] == "done" and g["audio_local_path"]]
        if done_gens:
            with st.expander(f"生成済み音源（全{len(done_gens)}件）", expanded=True):
                for g in done_gens:
                    st.audio(g["audio_local_path"])
