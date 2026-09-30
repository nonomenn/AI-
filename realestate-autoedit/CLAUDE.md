# CLAUDE.md

このリポジトリは、不動産ルームツアー動画(TikTok縦型・30〜40秒)の自動編集ツール。

- 仕様は `SPEC.md` が正。変更するときは仕様も更新すること
- 素材の受け渡し(SPEC 2章)
  - 撮影は外部の撮影者。縦向き・60fps・部屋ごとにクリップを分けて撮る
  - 動画と物件詳細資料(PDF・画像、間取り図入り)が LINE の「ファイル」送信で届く
  - 受け取ったら `物件動画/物件名/素材/` に動画、`物件動画/物件名/` 直下に物件資料を保存する
  - 広告画像・書体・BGM は `物件動画/共通/`(広告.png、フォント/、BGM/)
  - 本番の実行は `python -m autoedit 物件動画/物件名`。フォルダ名は `config/project.yaml`
- `property.yaml` は物件資料から自動生成する(`autoedit/intake.py`)。hook とキャッチ(傍点を付ける語は《》)の案を作り、既にあるファイルは上書きしない
  - コピーに「最高」「完璧」「日本一」など公正競争規約で根拠なく使えない語を入れない(`BANNED_TERMS`)
  - 物件情報は資料に書いてあることだけ。徒歩分数・駅名を推測で埋めない
- 素材は縦撮りが前提。横長素材の中央切り出しは予備扱い(ログで知らせる)
- 動画の読み込みは ffmpeg / ffprobe 経由(`autoedit/media.py`)。OpenCV の VideoCapture は日本語パスで失敗するので使わない
- 見た目の数値(テロップ位置、サイズ、トランジション、矢印の位置)はコードに直書きせず `config/style.yaml` に置く
- 構成(パートの順番・尺・カットの選び方)は `config/template.yaml`、部屋紹介の文言は `config/copy.yaml`
- 画面の座標はすべて 1080×1920 基準
- Claude API の呼び出しは `vision.ask_json`(JSONスキーマ指定)に集約する。既定モデルは `claude-opus-5-5`(`AUTOEDIT_MODEL` で変更)
- 変更したら `python -m pytest tests` を通す(実APIは呼ばない。`tests/test_e2e.py` は書き出しまで行うので約1分)
- テロップを変えたら、デモを書き出してフレームを切り出し、目で確認する
  `python -m autoedit --clips samples/clips --property samples/property_demo.yaml --labels samples/labels_demo.yaml --override samples/demo_override.yaml --out out/demo.mp4 --no-ai`
- CTAの矢印は TikTok のアカウントアイコン(中心 ≒ (953, 960))を指すこと。`python -m autoedit.preview` で確認する
- 派手なトランジション(スライド、スピン、グリッチなど)は入れない。上品でゆっくりが方針
- `物件動画/` と `out/` はコミットしない(撮影素材・物件資料は外部の方の著作物・個人情報を含む)
