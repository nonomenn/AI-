# AI導入支援アカウント（内部プロジェクト名：AI事業加速）

Instagram × X（Twitter）2軸運用によるSNS集客 → サービス・講座販売プロジェクト。

## 体制
- オーナー: （自分の名前）— 戦略・コンテンツ・最終承認
- COOエージェント: `coo`（root `CLAUDE.md`）

## 2プラットフォーム構成
| PF | フォルダ | 役割 | 主収益 |
|---|---|---|---|
| Instagram | `10_ai_biz/` | 信頼構築 → DM → 成約 | サービス・講座・顧問 |
| X（Twitter） | `20_x_twitter/` | 認知拡大 → 専門性訴求 | Instagram・相談への誘導 |

## 開発ルール
- 投稿企画 → Issue 起票 → ブランチ作成（`ig/` `x/` `service/` `ops/`）→ PR
- 全コンテンツPRは `compliance-reviewer` を通す
- セルフレビュー → 最終Approve → main マージ → 投稿
- 投稿後は KPI Issue で結果記録（72h以内）

## 設計書
- 全体設計：`00_strategy/master-plan.md`
- COO司令塔：`CLAUDE.md`

## 30日後の判定
30日経過時点でKPIが「見直し基準」に3項目以上該当 → 戦略・訴求軸を全面再設計。
判定基準は `CLAUDE.md` 参照。
