# AMPS — AI Music Production System

音楽制作会社の「企画・制作・品質管理・分析・改善」の仕組みをClaude Code上に再現するプロジェクト。
量産ツールではなく、1曲ごとの完成度を最優先し、月30曲を「ブランド資産」として積み上げることが目的。

## このシステムの特徴（今回の追加ポイント）

- **Trend Analysis（外部市場トレンド）は週1回・毎週月曜のみ実行。** 日次では回さない。
- **Post Insights Agent（新設）**：自分（自ブランド）のSNS投稿のうち**バズった投稿を検出し、なぜバズったかを分解して、次回の曲作り（Music Directorのブリーフ）に直接反映する**週次ループ。外部トレンドと自分の実績、両方をCEO Agentが週次企画の根拠にする。
- **Suno音源生成の自動化（オプション）**：`connectors/suno.py`から第三者Suno APIプロバイダーを呼び出し、Sunoプロンプト→実際の音源ファイルまで自動生成できる。**月間生成回数の上限（既定150回）をコード側で強制**し、プロバイダーの課金プランに関わらず上限を超えて呼び出さない安全装置つき。

## セットアップ

```bash
cd amps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # ANTHROPIC_API_KEY を設定
python -c "import db; db.init_db()"
streamlit run dashboard.py
```

常時自動運転したい場合（日次市場調査ログ＋週次Trend/PostInsights/CEO企画）：

```bash
python scheduler.py
```

## 使い方（ダッシュボード）

1. **ホーム**：曲一覧・ジャンル比率（目標70/20/10との対比）・最新の週次制作リスト。サイドバーから週次企画（Trend→PostInsights→CEO）を手動実行できる。
2. **新規企画**：テーマ・ジャンルを入力して「制作開始」→ 企画→歌詞→楽曲設計→Sunoプロンプト→品質評価まで自動生成。
3. **レビューキュー**：品質評価後（`qc_pending`）の曲を試聴・確認し、承認 or 差戻し（コメント付き）。
4. **自分の投稿分析**：SNS投稿の実績（再生・いいね・保存・シェア等）を記録。バズった投稿を自動判定し、Post Insights Agentのレポート（次回の曲作りへの示唆）を確認できる。
5. **曲詳細**：brief / 歌詞（版履歴）/ composition / suno_prompt / QC履歴を閲覧。

## 初回テスト

ダッシュボードの「新規企画」でテーマ「帰り道」を入力し、`songs/2026-07/001_kaerimichi/` と同じ流れ（企画→歌詞→設計→Sunoプロンプト→QC）が自動で再現されるか確認する。

## 中身

```
amps/
├── README.md                    ← このファイル
├── CLAUDE.md                    ← Claude Codeが最初に読む全体指示
├── AMPS_システム設計書.md         ← 全体設計（13エージェント・ワークフロー）
├── AMPS_Phase1_実装指示書.md      ← Phase 1の実装仕様
├── config.py / db.py / pipeline.py / dashboard.py / scheduler.py  ← 実装本体
├── agents/                      ← 13エージェントのプロンプト定義 + runner.py（共通実行器）
├── brand/brand_guideline.md     ← 全エージェントの判断軸（ブランド憲法）
├── songs/2026-07/001_kaerimichi/ ← 完成した1曲の実例（出力フォーマット基準）
├── database/                    ← 補助データ置き場（本体はamps.db、自動生成）
├── reports/                     ← 月次学習レポート
└── connectors/suno.py           ← Suno音源生成（オプション、SUNO_API_KEY設定で有効化）
```

## 事前に用意するもの

- Python 3.11+
- Anthropic APIキー（`.env` に `ANTHROPIC_API_KEY=...`）
- （任意）Suno音源生成を自動化したい場合：第三者Suno APIプロバイダーのAPIキー（`.env`に`SUNO_API_KEY`）。プリペイド・自動チャージOFFのプランを推奨。上限は`SUNO_MONTHLY_GENERATION_CAP`（既定150回/月）でコード側からも強制ブロックされる。

## 注意

- ブランド名など `brand/brand_guideline.md` の `[　]` は運営者が埋める箇所。
- Phase 1は「制作〜品質評価＋人の承認」と「自分の投稿実績→次回制作への反映」まで。配信・SNS投稿そのものの自動化はPhase 2以降。
- 歌詞・楽曲はオリジナルのみ。配信時はAI支援であることを正直に開示する方針。
