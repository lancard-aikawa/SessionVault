# SessionVault

設計は `docs/design.md` が正。仕様を変えたら先にそちらを直す。

- 実行時の依存は足さない（標準ライブラリだけ）。テストも `unittest`
- ファイルは必ず `encoding="utf-8"` で開く。JSONL を書くときは `newline="\n"` も付ける（Windows で CRLF にしない）。コピーはバイト列のまま行う
- `~/.claude/` を書き換えるのは `restore` と `repair --in-place` だけ。それ以外のコマンドで書き込む処理を入れない
- テストで本物の `~/.claude/projects` を読まない。`tempfile` で木を作って `--src` / `--vault` を渡す
- 知らない `type` のレコードは捨てずにそのまま扱う（Claude Code の版で増える）
