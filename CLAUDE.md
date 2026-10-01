# SessionVault

設計は `docs/design.md` が正。仕様を変えたら先にそちらを直す。

- 実行時の依存は足さない（標準ライブラリだけ）。テストも `unittest`
- ファイルは必ず `encoding="utf-8"` で開く。JSONL を書くときは `newline="\n"` も付ける（Windows で CRLF にしない）。コピーはバイト列のまま行う
- `~/.claude/` を書き換えるのは `restore` と `repair --in-place` だけ。それ以外のコマンドで書き込む処理を入れない
- テストで本物の `~/.claude/projects` を読まない。`tempfile` で木を作って `--src` / `--vault` を渡す
- 知らない `type` のレコードは捨てずにそのまま扱う（Claude Code の版で増える）
- 保管庫の中のパスは Windows の 260 文字を超える（世代名の `@時刻` と長い tool-results 名）。保管庫は `Vault` 経由で扱い（`long_path` で `\\?\` が付く）、テストの後片付けも `shutil.rmtree(long_path(...))` にする
- `scripts/*.cmd` は ASCII だけで書く。cmd は .cmd を cp932 として読むので、UTF-8 の日本語があると行が崩れて `set` まで壊れる（2026-10-01 に build-exe.cmd で実際に起きた）
- `scripts/build-exe.cmd` は `dist\sessionvault\` の設定ファイルと保管庫を退避してから作り直す。PyInstaller がフォルダを丸ごと消すため
- `<project-dir>` は大文字・小文字が揺れる（`C--...` と `c--...`）。突き合わせは大文字・小文字を無視する
- 設定のキーを足したら `config.py` の `DEFAULTS` と `_PARSERS`、`sessionvault.sample.json`、design.md §2.1 を一緒に直す
