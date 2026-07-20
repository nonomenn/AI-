# AMPS — AI Music Production System

音楽制作会社の「企画・制作・品質管理・分析・改善」の仕組みをClaude Code上に再現するプロジェクト。
量産ツールではなく、1曲ごとの完成度を最優先し、月30曲を「ブランド資産」として積み上げることが目的。

## このシステムの特徴（今回の追加ポイント）

- **Trend Analysis（外部市場トレンド）は週1回・毎週月曜のみ実行。** 日次では回さない。
- **Post Insights Agent（新設）**：自分（自ブランド）のSNS投稿のうち**バズった投稿を検出し、なぜバズったかを分解して、次回の曲作り（Music Directorのブリーフ）に直接反映する**週次ループ。外部トレンドと自分の実績、両方をCEO Agentが週次企画の根拠にする。
- **Suno音源生成の自動化（オプション）**：`connectors/suno.py`から[EvoLink](https://evolink.ai/suno)（99.9%稼働率SLA・自動フェイルオーバーのSuno APIプロバイダー）を呼び出し、Sunoプロンプト→実際の音源ファイルまで自動生成できる。**月間生成回数の上限（既定150回）をコード側で強制**し、プロバイダーの課金プランに関わらず上限を超えて呼び出さない安全装置つき。プリペイド・自動チャージOFFのプランで契約するのを推奨（$20〜30あれば改稿込み50曲/月をカバーできる想定）。

## セットアップ（ローカルPC）

AMPSは常時起動して使うツールなので、**自分のPC（Mac/Windows）にこの`amps/`フォルダを置いて**セットアップする。

### Mac / Linux
```bash
cd amps
./setup.sh
```
### Windows
`amps`フォルダの中の `setup.bat` をダブルクリック（またはコマンドプロンプトで実行）。

どちらも、venv作成・依存パッケージインストール・`.env`作成・DB初期化まで自動でやってくれる。完了後：

1. `.env` を開いて `ANTHROPIC_API_KEY` を設定（Suno音源生成を使うなら `SUNO_API_KEY` も）
2. 起動：
   ```bash
   source .venv/bin/activate   # Windowsは .venv\Scripts\activate.bat
   streamlit run dashboard.py
   ```

常時自動運転したい場合（日次市場調査ログ＋週次Trend/PostInsights/CEO企画）は、別ターミナルで：

```bash
python scheduler.py
```
を起動したままにしておく（PCのスリープを無効化推奨）。

## 使い方（ダッシュボード）

1. **ホーム**：曲一覧・ジャンル比率（目標70/20/10との対比）・最新の週次制作リスト。サイドバーから週次企画（Trend→PostInsights→CEO）を手動実行できる。
2. **新規企画**：テーマ・ジャンルを入力して「制作開始」→ 企画→歌詞→楽曲設計→Sunoプロンプト→品質評価まで自動生成。
3. **レビューキュー**：品質評価後（`qc_pending`）の曲を試聴・確認し、承認 or 差戻し（コメント付き）。
4. **自分の投稿分析**：SNS投稿の実績（再生・いいね・保存・シェア等）を記録。バズった投稿を自動判定し、Post Insights Agentのレポート（次回の曲作りへの示唆）を確認できる。
5. **曲詳細**：brief / 歌詞（版履歴）/ composition / suno_prompt / QC履歴を閲覧。

## 初回起動チェックリスト

- [ ] `streamlit run dashboard.py` が起動し、ブラウザ（自動で開く。開かない場合は http://localhost:8501 ）で表示される
- [ ] 「新規企画」でテーマ「帰り道」を入力→「制作開始」で、`songs/2026-07/001_kaerimichi/` と同様の一式（brief/lyrics/composition/suno_prompt/quality_review）が自動生成される
- [ ] 「レビューキュー」に生成した曲が表示され、承認・差戻し（コメント付き）が動く
- [ ] 「自分の投稿分析」で投稿実績を記録すると一覧に反映され、サイドバーの「週次企画を今すぐ実行」でPost Insightsレポートが生成される
- [ ] （`SUNO_API_KEY`設定時のみ）レビューキュー/曲詳細でSuno音源生成ボタンが動き、試聴できる
- [ ] `python scheduler.py` を起動したままにすると、毎週月曜にTrend Analysis→Post Insights→CEO企画が自動実行される

## 中身

```
amps/
├── README.md                    ← このファイル
├── CLAUDE.md                    ← Claude Codeが最初に読む全体指示
├── AMPS_システム設計書.md         ← 全体設計（13エージェント・ワークフロー）
├── AMPS_Phase1_実装指示書.md      ← Phase 1の実装仕様
├── setup.sh / setup.bat         ← ローカル一括セットアップ（Mac・Windows）
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
- （任意）Suno音源生成を自動化したい場合：[EvoLink](https://evolink.ai/suno)でAPIキーを取得し`.env`に`SUNO_API_KEY`を設定（プリペイド・自動チャージOFFのプランを推奨）。上限は`SUNO_MONTHLY_GENERATION_CAP`（既定150回/月）でコード側からも強制ブロックされる。別プロバイダーに変更する場合は`connectors/suno.py`のエンドポイント部分を書き換える。

## 注意

- ブランド名など `brand/brand_guideline.md` の `[　]` は運営者が埋める箇所。
- Phase 1は「制作〜品質評価＋人の承認」と「自分の投稿実績→次回制作への反映」まで。配信・SNS投稿そのものの自動化はPhase 2以降。
- 歌詞・楽曲はオリジナルのみ。配信時はAI支援であることを正直に開示する方針。
