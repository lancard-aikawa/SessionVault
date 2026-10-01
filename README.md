# SessionVault

Claude Code のセッション履歴 (`~/.claude/projects/` の JSONL) を、壊れても消えても戻せるように残しておく CLI。

- **backup** — セッションを保管庫にコピーする。元のファイルが縮んだり書き換わったりしても、前の版は世代として残す
- **verify** — 元のファイルと保管庫を検査する（JSON として読めない行、親子関係の切れ目、保管庫との食い違い）
- **repair** — 検査で見つかった壊れ方を直した版を書き出す
- **restore** — 保管庫から元の場所へ戻す

Python 標準ライブラリだけで動く。Claude History Viewer からはライブラリとして、RepoTether からは exe として呼ばれる想定。

> **状態: 骨組みだけ。**サブコマンドは引数を受け付けるが、中身はまだ無い（実行すると「未実装」で終わる）。
> 設計は [docs/design.md](docs/design.md)。

## なぜ作るか

Claude History Viewer (`F:\Repos\My\ClaudeChat`) の `claudehistory/archive.py` が既にバックアップを取っているが、

1. 元のファイルのサイズか更新時刻が変われば無条件に上書きする。元が途中で切れたり壊れたりすると、壊れた版で正しい版が消える
2. プロジェクト直下の `*.jsonl` しか見ていない。サブエージェントの記録 (`<session>/subagents/`) や長いツール結果 (`<session>/tool-results/`) が残らない
3. Viewer を起動しているあいだしか動かない

この 3 点を、Viewer から切り離した道具として直す。

## 使い方（予定）

```cmd
uv run sessionvault backup                 :: ~/.claude/projects を保管庫へ
uv run sessionvault verify                 :: 元と保管庫を検査（問題があれば終了コード 1）
uv run sessionvault verify --json          :: RepoTether 向けの機械可読な出力
uv run sessionvault repair <session-id> --out fixed.jsonl
uv run sessionvault restore <session-id>
```

保管庫の場所は `--vault`、環境変数 `SESSIONVAULT_DIR`、既定の `~/.sessionvault` の順で決まる。

## 開発

```cmd
uv sync
uv run python -m unittest discover -s tests
uv run sessionvault --help
```

- Python 3.10 以上、実行時の依存なし
- ファイルを開くときは必ず `encoding="utf-8"` を付ける
- `~/.claude/` の中身は、`restore` と `repair --in-place` 以外では書き換えない
