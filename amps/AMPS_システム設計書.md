# AMPS（AI Music Production System）設計書

## 0. プロジェクトの位置づけ

本システムは「AI楽曲を大量生産するツール」ではなく、**音楽制作会社の企画・制作・品質管理・分析・改善の仕組みをClaude Code上に再現するもの**です。私（Claude）はプロデューサー／COOとして、市場分析から改善提案までを一貫して担当します。

- 月間目標：30曲（量産ではなく資産化が目的）
- ジャンル比率：ラブソング70% / 応援ソング20% / ボカロ系10%
- 判断基準：常に「なぜこの曲を作るのか」を論理的に説明できること

---

## 1. エージェント構成と役割

| Agent | 役割 | 主な入力 | 主な出力 |
|---|---|---|---|
| CEO Agent | 週次の制作曲を決定 | 市場分析・過去データ・ブランド適合度 | 週次制作リスト |
| Market Research Agent | 日次市場調査 | Spotify/TikTok/YouTube/Billboardの公開情報 | 市場データレポート |
| Trend Analysis Agent | トレンド抽出 | 市場データ | 伸びているキーワード・要素 |
| Music Director Agent | 制作テーマ決定 | トレンド＋ブランド | テーマ・世界観ブリーフ |
| Lyrics Agent | 作詞（最重要） | テーマブリーフ | 歌詞＋主人公設計書 |
| Composition Agent | 楽曲設計 | 歌詞・テーマ | BPM/Key/コード進行/構成表 |
| Suno Prompt Agent | Suno用英語プロンプト生成 | 楽曲設計＋歌詞 | 高精度プロンプト（長文） |
| Quality Check Agent | 品質評価・改善指示 | 生成曲＋歌詞＋設計 | 100点満点評価＋改善案 |
| Branding Agent | ブランド統一管理 | 全成果物 | タイトル/ジャケ/MV/SNS文言 |
| Release Agent | 配信用データ生成 | 楽曲＋ブランド情報 | 各プラットフォーム用テキスト一式 |
| Analytics Agent | 配信後データ分析 | 各種再生・保存指標 | 分析レポート |
| Post Insights Agent | 自ブランドのSNS投稿実績を分析（週次） | 自分の投稿の再生/いいね/保存等 | バズった投稿の要因分析＋次回制作への示唆 |
| Learning Agent | 月次学習・改善（最重要） | 全楽曲データベース | 成功/失敗要因＋改善提案 |

### 注意点（重要）
- 市場調査は「公開されている統計情報・ランキング傾向」を対象とし、他者の歌詞や記事本文をそのまま複製することはしません。参考にする場合も要約・独自分析に留めます。
- Suno等で生成した楽曲・歌詞は必ずオリジナルであることを前提とし、既存曲の歌詞やメロディの模倣（似せすぎ）は避けます。

---

## 2. 週次ワークフロー

```
月曜: Market Research（直近1週間分）→ Trend Analysis（週1回） → Post Insights（週1回・自曲バズ分析） → CEO Agentが今週の制作曲を決定
火曜: Music Director → Lyrics Agent（初稿）
水曜: Lyrics Agent（改稿）→ Composition Agent
木曜: Suno Prompt Agent → 楽曲生成 → Quality Check（1回目）
金曜: 改善→ Quality Check（2〜3回目）→ 80点未満は再制作
土曜: Branding Agent → Release Agent（配信データ作成）
日曜: リリース／Analytics Agentが前週分の効果測定
```

月次：Learning Agentが全曲データを振り返り、次月の制作方針に反映。

**Trend Analysis と Post Insights はどちらも週1回（月曜）実行。**
Trend Analysisは外部市場、Post Insightsは自分の投稿実績という異なる情報源を扱い、両方をCEO Agentが週次企画の判断材料にする。

---

## 3. フォルダ構成（Claude Codeプロジェクト）

```
amps/
├── CLAUDE.md                     # プロジェクト全体指示（本設計書の要約）
├── agents/                       # 各エージェントのプロンプト定義
│   ├── ceo_agent.md
│   ├── market_research_agent.md
│   ├── trend_analysis_agent.md
│   ├── music_director_agent.md
│   ├── lyrics_agent.md
│   ├── composition_agent.md
│   ├── suno_prompt_agent.md
│   ├── quality_check_agent.md
│   ├── branding_agent.md
│   ├── release_agent.md
│   ├── analytics_agent.md
│   └── learning_agent.md
├── brand/
│   └── brand_guideline.md
├── songs/
│   └── 2026-07/
│       └── 001_song-title/
│           ├── brief.md          # テーマ・世界観
│           ├── lyrics.md         # 歌詞（改訂履歴含む）
│           ├── composition.md    # BPM/Key/構成
│           ├── suno_prompt.md
│           ├── quality_review.md
│           ├── release_assets.md
│           └── analytics.md
├── database/
│   ├── songs_db.csv              # 全曲マスタ
│   ├── lyrics_db.csv
│   ├── prompts_db.csv
│   └── analytics_db.csv
└── reports/
    └── monthly_learning_2026-07.md
```

---

## 4. 主要テンプレート

### 4-1. 週次制作ブリーフ（Music Director → Lyrics Agent）
```
テーマ：
主人公（年齢・性別・状況）：
世界観・季節・時間帯：
ストーリー構成（起承転結）：
感情の変化（Aメロ→サビ→ラスサビ）：
参考トレンド要素：
ジャンル区分：ラブソング／応援ソング／ボカロ系
```

### 4-2. 歌詞NGルール（Lyrics Agentが自己チェック）
- 抽象語だけで終わる歌詞（禁止）
- 意味のない英語混入（禁止）
- 語尾の3回以上連続（禁止）
- テンプレ恋愛表現のみ（禁止）
- AIっぽい説明的すぎる文章（禁止）

### 4-3. 品質評価シート（Quality Check Agent）
| 項目 | 配点 |
|---|---|
| 歌詞の独自性・感情表現 | 20 |
| メロディ適合性 | 15 |
| 構成（サビ配置・展開） | 15 |
| 中毒性・リピート性 | 15 |
| 歌いやすさ | 10 |
| ブランド一致度 | 10 |
| Spotify/TikTok適性 | 15 |
| **合計** | **100** |

80点未満 → 改善案を提示し再制作。最低3回レビュー。

### 4-4. Sunoプロンプト構成要素
```
[Genre/Style] [Mood] [Tempo/BPM] [Key] [Vocal type/tone]
[Instrumentation] [Song structure: intro-verse-chorus...]
[Emotional arc] [Reference feel, not copy]
```
※既存アーティストの模倣指定ではなく「〜のような温かみのある女性ボーカル」等の抽象的表現で音楽性を伝える。

---

## 5. データベース設計（CSV/簡易DB）

**songs_db.csv**
`song_id, title, genre, theme, release_date, bpm, key, status, quality_score`

**analytics_db.csv**
`song_id, platform, date, plays, saves, playlist_adds, completion_rate, CTR, retention`

**lyrics_db.csv**
`song_id, version, lyrics_text, revision_notes`

これらはLearning Agentが月次で読み込み、成功パターン（高保存率・高完走率の曲に共通する構成・テーマ）を抽出します。

---

## 6. ブランドガイドライン（初期案・要調整）

- ブランドコンセプト：「5年後も聴かれる曲」
- トーン：誠実・繊細・過度に商業的でない
- ビジュアル：統一感のある色調・フォント（別途Branding Agentで詳細化）
- SNS発信：曲の背景ストーリーを添える（世界観の一貫性）

---

## 次のステップ

以下のいずれかから着手できます。
1. `agents/`配下の各エージェントの詳細プロンプト（12ファイル）を作成する
2. `CLAUDE.md`（プロジェクト全体指示ファイル）を作成する
3. 実際に1曲分（テーマ→歌詞→Sunoプロンプトまで）のサンプル制作フローを走らせてみる

どこから進めますか？
