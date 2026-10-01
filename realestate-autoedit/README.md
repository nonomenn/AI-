# realestate-autoedit

不動産ルームツアー動画(TikTok 縦型・30〜45秒)を、撮影素材と物件資料から自動で編集するツール。仕様は `SPEC.md`。

## 必要なもの

- Python 3.10以上
- ffmpeg(ffprobe も。PATH が通っていること)
- `pip install -r requirements.txt`
- AI(物件資料の読み取り・部屋判定)を使う場合は、環境変数 `ANTHROPIC_API_KEY` を設定する

## 使い方(本番)

1. LINE の「ファイル」で届いた動画と物件資料を、次のように保存する

   ```
   物件動画/
     共通/            広告.png、BGM/、フォント/(全物件で共通。最初に1回だけ用意)
     阿波座○○/
       素材/          ← 動画(部屋ごとのクリップ)
       物件資料.pdf    ← PDF・画像(間取り図入り)を直下に
       サムネ写真.jpg  ← サムネに使う写真(任意。名前に「サムネ」を含める)
   ```

2. 実行する

   ```bash
   python -m autoedit 物件動画/阿波座○○
   ```

   - 物件資料から物件情報と間取り図を読み取り、hook とキャッチの案を作って `property.yaml` を自動生成する
   - `阿波座○○/出力/` に、動画 `阿波座○○.mp4`、サムネ `_サムネ.jpg`(黒×ゴールド)、投稿文 `_投稿.txt`(投稿タイトル・キャプション)、構成表 `_plan.json` ができる
   - 物件番号(No.L###)は `property.yaml` の `number` か `--number L036`。無ければ前回の +1

3. 文言を直したいときは `property.yaml` を編集して、もう一度実行する(`property.yaml` は上書きされない)

```bash
# 物件資料の読み取りだけ行う / 作り直す
python -m autoedit.intake 物件動画/阿波座○○ [--force]

# 構成表だけ確認する(書き出さない)
python -m autoedit 物件動画/阿波座○○ --plan-only

# 矢印がアカウントアイコンを指しているか確認する(省略時は最後から1秒前のコマ)
python -m autoedit.preview 物件動画/阿波座○○/出力/阿波座○○.mp4 --out cta_check.png

# 使われる書体の確認
python -m autoedit.fonts 物件動画/共通/フォント
```

## ドライブに自動保存

完成品(`完成/No.L###_物件名/` の動画・サムネ・キャプション)を、実行のたびに Google ドライブの `完成動画/No.L###_物件名/` に保存できる。方法は2つ。

**A. 自分のパソコンで動かす場合(いちばん簡単)**: 「Google ドライブ パソコン版」を入れ、`config/project.yaml` の `publish_dir` をドライブの同期フォルダ(例: `G:/マイドライブ/完成動画`)にする。それだけで自動で同期される。

**B. クラウド(Claude Code)で動かす場合**: 自分の Google アカウントに「受け口」を1回だけ作る(5分)。

1. https://script.google.com を開き「新しいプロジェクト」
2. `tools/drive_upload.gs` の中身を全部貼り付け、`KEY` を自分で決めた長い文字列(合言葉)に変えて保存
3. 右上の「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」。実行ユーザー「自分」、アクセスできるユーザー「全員」→「デプロイ」→ Google アカウントでアクセスを承認
4. 表示された「ウェブアプリの URL」と合言葉を、環境の設定(画面上部の環境メニュー →「編集」)に環境変数として登録する
   - `AUTOEDIT_DRIVE_URL` = ウェブアプリの URL
   - `AUTOEDIT_DRIVE_KEY` = 合言葉
   - 合言葉はチャットに書かない。次のセッションから有効になる

合言葉を知っている人だけが保存でき、ドライブのパスワードや認証情報はツールに渡らない。1ファイル35MBまで(36秒前後の動画は約30MB)。手動で送るときは `python -m autoedit.drive_upload 物件動画/完成/No.L036_物件名`。

## デモ(同梱のテスト素材で実行)

```bash
python -m autoedit --clips samples/clips --property samples/property_demo.yaml \
  --labels samples/labels_demo.yaml --override samples/demo_override.yaml --out out/demo.mp4 --no-ai
```

テスト素材は、参考動画(360p・編集済み・横長)を切り分けたもの。画質が粗いのと、使える区間が少なく尺が約19秒になるのは素材の都合。`labels_demo.yaml` は、本来 AI が自動で出す判定結果を手で書いたもの。

## テスト

```bash
python -m pytest tests
```

Claude API は応答を差し替えて検証するので、APIキーは不要。`test_e2e.py` は合成した縦長 60fps 素材で物件フォルダ指定の実行を書き出しまで行う(約1分)。

## ファイル構成

```
autoedit/
  cli.py       入口(物件フォルダ指定 / 個別指定)
  project.py   物件フォルダ(素材・物件資料・共通素材)の解決
  intake.py    物件資料の読み取り → property.yaml・floorplan.json の自動生成
  media.py     ffmpeg / ffprobe での動画読み込み(回転メタデータ・日本語パス対応)
  analyze.py   素材解析(移動・手ブレ・ピンボケを除外し、安定区間を抽出)
  vision.py    Claude API による部屋判定・映え度・間取り図の読み取り
  planner.py   構成の組み立て(見所→キャッチ→広告→START→部屋紹介→映え+CTA)
  telop.py     テロップの描画とアニメーション
  render.py    合成と書き出し(ゆっくり寄り・トランジション・テロップ・BGM)
  fonts.py     書体ファイルの解決
  preview.py   TikTokのUI位置ガイドを重ねた確認画像
  thumbnail.py サムネイル(黒×ゴールドのテンプレート)
  post.py      物件番号・投稿タイトル・キャプションと納品前チェック
  drive_upload.py  完成品を Google ドライブへ保存(tools/drive_upload.gs 経由)
tools/
  drive_upload.gs  ドライブ保存の受け口(自分の Google アカウントに置く Apps Script)
config/
  project.yaml   物件フォルダの構成
  style.yaml     見た目の設定(位置・サイズ・書体・トランジション・矢印)
  template.yaml  構成テンプレート
  copy.yaml      部屋紹介の文言
tests/           自動テスト
```
