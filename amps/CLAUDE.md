# CLAUDE.md — AMPS（AI Music Production System）

このリポジトリは、AI楽曲を大量生産するためのものではありません。
**音楽制作会社が持つ「企画・制作・品質管理・分析・改善」の仕組みをClaude Code上に再現する**プロジェクトです。
Claude Code はこのファイルを最初に読み、以下の原則に従って作業してください。

---

## プロジェクトの目的

- 月30曲を「ブランド資産」として積み上げる。量産ではなく1曲ごとの完成度を最優先。
- 目標：Spotify / Apple Music / YouTube Music 等で継続的に聴かれる「5年後も残る曲」。
- 毎回「なぜこの曲を作るのか」を論理的に説明できる状態を保つ。

## 制作ジャンル（これ以外は制作・提案しない）

1. ラブソング（約70%）
2. 応援ソング（約20%）
3. ボカロ系（約10%）

EDM / HipHop / Trap / K-POP / 演歌 / ジャズ 等は対象外。

## エージェント運用の鉄則

- 13のエージェント定義は `agents/*.md` にある。**各エージェントの振る舞いはそのmdをシステムプロンプトとして使う**こと（`agents/runner.py` が実装）。ロジックをコードに直書きしない。
- 週次の基本フロー：
  `market_research(日次) → trend_analysis(週1回) → post_insights(週1回) → ceo → music_director(brief) → lyrics → composition → suno_prompt → quality_check → branding → release → analytics → learning`
- 判断に迷ったら `brand/brand_guideline.md` に従う。

## トレンド分析・自曲投稿インサイトの実行頻度（重要）

- **Trend Analysis Agent（外部市場トレンド）は週1回、毎週月曜のみ実行する。** 日次では回さない。Market Research Agentが日次で集めた1週間分をまとめて読む。
- **Post Insights Agent（自分のバズった投稿の分析）も同じく週1回、毎週月曜に実行する。**
  自分（自ブランド）のSNS投稿実績（`database/posts`）からバズった投稿とその要因を分析し、**次回の曲作り（Music Directorのブリーフ）に直接反映する**のがこのシステムの中核ループ。
  - Trend Analysis＝外部市場、Post Insights＝自分の実績、という別ソースを両方CEO Agentに渡し、週次制作リストの根拠にする。
  - ダッシュボードの「自分の投稿分析」ページから投稿実績を記録できる。

## 品質と承認

- Quality Check Agentは100点満点で評価し、80点未満は改善して再制作（最低3回レビュー）。
- **人の承認ゲートを2箇所置く**：①QC後（試聴して承認/差戻し）②公開前。ここは自動化しない。

## Suno音源生成（オプション、`connectors/suno.py`）

- Suno公式は開発者向けAPIを一般公開していないため、第三者Suno APIプロバイダー（[EvoLink](https://evolink.ai/suno)を採用、99.9%稼働率SLA・自動フェイルオーバー）経由での連携を前提にしている。
- `SUNO_API_KEY`が`.env`に設定されている場合のみ、ダッシュボードの「レビューキュー」「曲詳細」から音源生成ボタンが使える。
- **月間生成回数の上限（`SUNO_MONTHLY_GENERATION_CAP`、既定150回）をコード側で強制**する。課金プロバイダーの設定に関わらず、上限に達したら`SunoQuotaExceeded`で呼び出し自体をブロックする。プロバイダー契約はプリペイド・自動チャージOFFを推奨。

## コンプライアンス（必須）

- 歌詞・楽曲はオリジナルのみ。既存曲の歌詞・メロディ、実在アーティストの模倣をしない。
- 市場調査は公開情報の傾向把握に留め、他者の文章を複製しない。
- 配信時はAI支援であることを正直に開示する。配信は間隔を空け、重複・水増しをしない。

## 実装スコープ

- 現在は **Phase 1**：企画→作詞→楽曲設計→Sunoプロンプト→品質評価までを半自動化し、ダッシュボードで承認する。
- 詳細仕様は `AMPS_Phase1_実装指示書.md` に従う。
- 投稿（配信/SNS）そのものの自動化と、楽曲の配信後アナリティクス（Analytics/Learning Agent連携）はPhase 2以降。`connectors/` を後付けできる構造にしておく。
- ただし「自分の投稿実績を記録して次回の曲作りに活かす」ループ（Post Insights Agent）はPhase 1から有効。投稿実績の入力は当面ダッシュボードから手動。

## 技術スタック（Phase 1・確定）

- Python / anthropic SDK / Streamlit / APScheduler / SQLite / python-dotenv
- APIキーは `.env`（`ANTHROPIC_API_KEY`）。リポジトリにコミットしない。

## セットアップ

```
cd amps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY を設定
python -c "import db; db.init_db()"
streamlit run dashboard.py
```

常時自動運転したい場合は別プロセスで `python scheduler.py`（日次市場調査＋週次Trend/PostInsights/CEO企画）を起動する。

## ディレクトリ

```
agents/   … 13エージェント定義（システムプロンプト）＋ runner.py（共通実行器）
brand/    … brand_guideline.md（判断の憲法）
songs/    … 曲ごとの成果物（brief/lyrics/composition/suno_prompt/quality_review）
database/ … 補助データ置き場（本体はamps.db / SQLite、自動生成）
reports/  … 月次学習レポート
config.py / db.py / pipeline.py / agents/runner.py / dashboard.py / scheduler.py … Phase1実装本体
```

## 参考：完成した1曲の出力例

`songs/2026-07/001_kaerimichi/` に、テーマ「帰り道」で企画→歌詞→設計→Sunoプロンプト→QC評価まで通した**実例**が入っている。各エージェントの出力フォーマットの基準として参照すること。
