# 作業手順書（1人運用版）

このドキュメントは、Gitに不慣れでも作業を進められるように書かれています。

---

## TL;DR（要点3行）

1. 作業前に `git pull origin main`（最新化）
2. ブランチを切って作業（`content/` `service/` `ops/` の3パターン）
3. `git add → commit → push → gh pr create` でレビュー・マージ

---

## §0 用語集

| 用語 | 意味 |
|---|---|
| **リポジトリ** | ファイル一式をまとめた「箱」 |
| **commit** | 変更を「ここまでやった」と記録すること |
| **push** | 自分の変更をGitHubに送ること |
| **pull** | GitHubから最新版を取得すること |
| **branch** | 自分専用の作業コピー。本番（main）を汚さずに実験できる |
| **PR** | 「自分の変更を本番に取り込んで」という申請 |

---

## §1 最初の1回だけの準備

```bash
# GitHub CLIのインストール（Mac）
brew install gh

# GitHubにログイン
gh auth login

# リポジトリをダウンロード
gh repo clone your-username/ai-biz-accel
cd ai-biz-accel
```

---

## §2 毎回の作業フロー

### 2-1. 作業開始：最新化（必須）
```bash
git pull origin main
```

### 2-2. ブランチを切る

| 作業内容 | ブランチ名の例 |
|---|---|
| 投稿コンテンツ | `content/2026-05-02-chatgpt-eigyo` |
| サービス・LP | `service/2026-05-02-consultation-lp` |
| 運用・設定 | `ops/2026-05-02-profile-update` |

```bash
git checkout -b content/2026-05-02-chatgpt-eigyo
```

### 2-3. ファイルを編集・追加

Claude Codeに「この投稿の台本書いて」「提案文作って」と頼んでもOK。

### 2-4. 変更を記録・送信
```bash
git add .
git commit -m "コンテンツ: ChatGPT営業活用Reels台本"
git push -u origin content/2026-05-02-chatgpt-eigyo
```

### 2-5. PRを作成してマージ
```bash
gh pr create --base main \
  --title "コンテンツ: ChatGPT営業活用Reels台本" \
  --body "Issue #X に紐付け。compliance-reviewer 確認済み。"
```

セルフレビュー後、PRをマージ。

### 2-6. 後片付け
```bash
git checkout main
git pull origin main
git branch -d content/2026-05-02-chatgpt-eigyo
```

---

## §3 エージェント一覧

| エージェント | 何をしてくれる | 呼ぶタイミング |
|---|---|---|
| **coo** | 進捗管理・優先順位決定 | 週次レビュー時 |
| **content-strategist** | 投稿企画の設計 | 投稿テーマを考える時 |
| **short-video-scriptwriter** | Reels台本作成 | 動画台本が必要な時 |
| **service-sales-writer** | DM・提案文・LP作成 | 商談・成約フローの整備時 |
| **compliance-reviewer** | 表現リスク確認 | コンテンツ完成後・PR出す前 |
| **knowledge-curator** | 学び・事例の蓄積 | 投稿後の振り返り時 |

---

## §4 リポジトリ構造

```
ai-biz-accel/
├── CLAUDE.md            ← COO司令塔（AIへの指示書）
├── README.md            ← プロジェクト概要
├── .github/             ← Issue/PRテンプレ
├── .claude/             ← AI助手の定義
│   ├── agents/          ← 6エージェント
│   └── skills/          ← ブランドボイス
├── 00_strategy/         ← 戦略・意思決定ログ
├── 10_ai_biz/           ← コンテンツ・KPI・戦略
├── 40_analytics/        ← KPI・分析レポート
├── 50_knowledge/        ← ナレッジ蓄積
└── 60_operations/       ← 運用手順（このファイルもここ）
```

---

## §5 SLA（自分への約束）

| アクション | SLA |
|---|---|
| AIが投稿PRを出す | 24h以内 |
| セルフレビュー | 48h以内 |
| 投稿実行 | Approve後24h以内 |
| 結果記録 | 投稿後72h以内 |

---

最終更新：2026-05-04
