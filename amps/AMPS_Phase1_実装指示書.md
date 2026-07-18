# AMPS Phase 1 実装指示書（Claude Code向け）

このドキュメントはClaude Codeにそのまま渡して実装させるための仕様書です。
既存の `agents/*.md`（12エージェントのプロンプト定義）と `AMPS_システム設計書.md` を前提とします。

---

## 0. Phase 1のゴール（完了条件 / DoD）

**「テーマを1つ入力すると、企画→作詞→楽曲設計→Sunoプロンプト→品質評価までを自動生成し、ダッシュボードで人が試聴・承認できる」半自動システムをローカルPCで動かす。**

- 投稿（配信/SNS）と分析はPhase 1では対象外（手動）。
- 全成果物がSQLiteと `songs/` フォルダに残る。
- 承認ゲート：品質評価(QC)後に人が「承認 / 差戻し」を押す。差戻しはLyrics/Compositionを再実行する。

---

## 1. 設計原則（必ず守る）

- 量産ではなく品質優先。1曲ごとの完成度を最大化する。
- 各エージェントは `agents/{name}.md` をシステムプロンプトとして使う。ロジックをコードに直書きしない。
- 既存楽曲の歌詞・メロディ・実在アーティストの模倣をしない（プロンプト側で制御済み。生成物にもチェックを入れる）。
- ジャンルはラブソング/応援ソング/ボカロ系のみ。比率 70/20/10 をダッシュボードで可視化する。
- 全処理はローカル完結。外部送信はAnthropic APIのみ（Phase 1時点）。

---

## 2. 確定技術スタック

| 要素 | 採用 |
|---|---|
| 言語 | Python 3.11+ |
| エージェント実行 | anthropic（公式SDK） |
| ダッシュボード | Streamlit |
| スケジューラ | APScheduler（プロセス内蔵、Phase1では手動起動でも可） |
| DB | SQLite（標準ライブラリ sqlite3） |
| 設定管理 | python-dotenv（.env に ANTHROPIC_API_KEY） |

`requirements.txt`：
```
anthropic
streamlit
apscheduler
python-dotenv
```

環境変数（`.env.example` を用意）：
```
ANTHROPIC_API_KEY=sk-...
AMPS_MODEL=（現行の適切なClaudeモデル名。設定で差し替え可能にする）
```

---

## 3. ディレクトリ構成

```
amps/
├── CLAUDE.md                 # プロジェクト全体指示（下記4で作成）
├── .env.example
├── requirements.txt
├── config.py                # 環境変数・パス・モデル名の集約
├── db.py                     # SQLite初期化とCRUDヘルパー
├── pipeline.py               # オーケストレーター（状態機械）
├── scheduler.py              # APScheduler（週次企画・日次調査のトリガ）
├── dashboard.py              # Streamlitアプリ（人の操作卓）
├── agents/
│   ├── runner.py             # agents/*.md を読み込みClaude APIを呼ぶ共通実行器
│   └── *.md                  # 作成済みの12エージェント定義
├── brand/
│   └── brand_guideline.md
├── songs/                    # 曲ごとの成果物（md）を保存
└── amps.db                   # SQLite本体（自動生成）
```

---

## 4. CLAUDE.md に書く内容（プロジェクト起動時の指示）

- AMPSの目的（音楽制作会社の仕組みの再現。量産ではない）。
- ジャンルと比率、ブランド方針（5年後も聴かれる曲）。
- 「各エージェントは agents/*.md をシステムプロンプトとして使う」ルール。
- 著作権・模倣禁止の原則。
- Phase 1のスコープ（生成〜QC承認まで、投稿は手動）。

---

## 5. データベース設計（SQLite DDL）

```sql
CREATE TABLE songs (
  song_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  title       TEXT,
  genre       TEXT,           -- love / cheer / vocaloid
  theme       TEXT,
  status      TEXT NOT NULL,  -- 下記ステータス参照
  quality_score INTEGER,
  week_of     TEXT,           -- 例 2026-07-13
  created_at  TEXT DEFAULT (datetime('now')),
  updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE briefs (
  song_id INTEGER PRIMARY KEY,
  content TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE lyrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER,
  version INTEGER,
  content TEXT,
  revision_notes TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE compositions (
  song_id INTEGER PRIMARY KEY,
  bpm INTEGER, key TEXT, structure TEXT, content TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE suno_prompts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER, version INTEGER,
  style_prompt TEXT, formatted_lyrics TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE quality_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER, round INTEGER,
  score INTEGER, breakdown_json TEXT,
  verdict TEXT,     -- pass / redo
  notes TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(song_id) REFERENCES songs(song_id)
);

CREATE TABLE agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER, agent TEXT,
  input_summary TEXT, output_summary TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
```

**status の遷移（Phase 1）**
```
planned → brief_done → lyrics_done → composed → prompted → qc_pending
  → (人が承認) qc_passed
  → (人が差戻し) lyrics_done へ戻り再実行
```

---

## 6. モジュール別の責務

### config.py
`.env` 読み込み、モデル名、各種パス、ジャンル定数・比率目標を定義。

### db.py
- `init_db()`：テーブル未作成なら作る。
- CRUDヘルパー：`create_song`, `update_status`, `save_brief`, `save_lyrics`, `save_composition`, `save_prompt`, `save_review`, `get_song`, `list_songs`, `list_by_status` など。

### agents/runner.py
- `run_agent(agent_name, upstream_text, extra_context="")`：
  1. `agents/{agent_name}.md` を読み込みシステムプロンプトにする。
  2. 上流成果物（brief, lyrics 等）をユーザーメッセージとして渡す。
  3. Anthropic SDKで呼び出し、テキスト出力を返す。
  4. `agent_runs` にログを残す。
- 失敗時はリトライ（指数バックオフ）。

### pipeline.py（オーケストレーター）
- `advance(song_id)`：現在のstatusを見て「次の1エージェント」を実行し、成果物を保存、statusを進める。
- `run_full(song_id)`：planned から qc_pending まで一気に流す。
- QC結果が80点未満なら自動でLyrics/Compositionを再実行（最大3回）。3回で80未満なら qc_pending のまま人へ回す（要改善フラグ付き）。
- 対応するエージェント順：
  `ceo(任意)→ music_director(brief)→ lyrics→ composition→ suno_prompt→ quality_check`

### scheduler.py
- APSchedulerで「週次：CEO企画」「日次：市場調査（Phase1では簡易ログのみでも可）」を登録。
- Phase 1では手動起動でも可（ダッシュボードのボタンからトリガできれば十分）。

### dashboard.py（Streamlit）
画面要件：
1. **ホーム**：今週の曲一覧（タイトル/ジャンル/status/QCスコア）＋ジャンル比率バー（目標70/20/10との対比）。
2. **新規企画**：テーマ・ジャンルを入力 →「制作開始」ボタンで `run_full` を非同期起動。
3. **レビューキュー**：status=`qc_pending` の曲を表示。歌詞・Sunoプロンプト・QC採点内訳を並べ、Sunoプロンプトは**コピーボタン**付き。[承認]→qc_passed、[差戻し]（コメント入力可）→再実行。
4. **曲詳細**：brief / lyrics（版履歴）/ composition / suno_prompt / QC履歴 を全て閲覧。

---

## 7. Claude Codeへのタスク分解（この順で実装）

1. プロジェクト初期化：`requirements.txt`、`.env.example`、`config.py`、`CLAUDE.md`。
2. `db.py`：DDL適用とCRUDヘルパー。`python -c "import db; db.init_db()"` で動作確認。
3. `agents/runner.py`：`agents/lyrics_agent.md` を使ってテスト1回呼び出し、出力が返ることを確認。
4. `pipeline.py`：brief→lyrics→composition→suno_prompt→quality_check の状態遷移。QC自動再実行（最大3回）まで。
5. `dashboard.py`：ホーム／新規企画／レビューキュー／曲詳細。承認・差戻しを実装。
6. `scheduler.py`：週次・日次トリガ（Phase 1は手動起動でも可）。
7. 通し確認：テーマ「帰り道」で新規企画→ qc_pending まで自動生成→ ダッシュボードで承認 → qc_passed。成果物がDBと `songs/` に残ることを確認。

---

## 8. Phase 2以降の接続点（今は作らないが構造を空けておく）

- `connectors/` フォルダを想定（youtube.py, instagram.py, x.py, tiktok.py, suno.py, distributor.py）。
- pipelineに `released` / `analyzed` ステートを後から追加できるよう、status文字列で管理しておく。
- **配信は投稿間隔を空ける設計にする**（スパム検知回避）。AI使用の開示（DDEX）を前提に、release_assetsへ「AI開示：あり」を必ず持たせる。

---

## 9. 注意（運用・コンプライアンス）

- ローカルPC常時起動で運用。スリープ無効化を推奨（電源設定）。
- Anthropic APIキーは `.env` に置き、リポジトリにコミットしない（`.gitignore`）。
- 生成された歌詞・楽曲はオリジナル前提。QC Agentのチェック項目に「既存曲との酷似がないか」を含める。
- 配信段階では各プラットフォームのAI開示ルールに従い、正直に申告する。
