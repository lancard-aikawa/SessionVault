# SessionVault

Claude Code のセッション履歴 (`~/.claude/projects/` の JSONL) を、壊れても消えても戻せるように残しておく CLI。

- **backup** — セッションを保管庫にコピーする。元のファイルが縮んだり書き換わったりしても、前の版は世代として残す
- **verify** — 元のファイルと保管庫を検査する（JSON として読めない行、親子関係の切れ目、保管庫との食い違い）
- **repair** — 検査で見つかった壊れ方を直した版を書き出す
- **restore** — 保管庫から元の場所へ戻す

Python 標準ライブラリだけで動く。Claude History Viewer からはライブラリとして、RepoTether からは exe として呼ばれる想定。

memory（`~/.claude/projects/<project>/memory/`）も世代付きで残す。セッションの記録から「どの会話でその memory を書いたか」を拾い、memory を会話の索引として使えるようにする（`memory-index`）。

> **状態: 作りかけ。**動くのは `config`・`backup`・`prune`・`verify`。ほかのサブコマンドは引数を受け付けるが、実行すると「未実装」で終わる。
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

## 設定

保管庫は既定でプログラムの置き場所の下（exe ならそのフォルダ、リポジトリから動かすならリポジトリ直下）の `vault/` に作る。
設定は同じ場所の `sessionvault.json`（見本: [sessionvault.sample.json](sessionvault.sample.json)）。手で書いても、コマンドで変えてもよい。

```cmd
uv run sessionvault config show                              :: 今の設定と、実際に使う保管庫の場所
uv run sessionvault config set vault F:/Backup/SessionVault  :: 保管庫を移す（中身は自動では移さない）
uv run sessionvault config set retention.max_generations 20  :: 1 ファイルあたり 20 世代まで残す
uv run sessionvault config set retention.max_age_days null   :: 日数では消さない
```

保管庫の場所は `--vault` → 環境変数 `SESSIONVAULT_DIR` → 設定の `vault` → `<置き場所>/vault` の順で決まる。
世代の間引き（`retention`）は既定では何も消さない。詳しくは [docs/design.md §2.1・§3.1](docs/design.md)。

## 開発

```cmd
uv sync
uv run python -m unittest discover -s tests
uv run sessionvault --help
```

- Python 3.10 以上、実行時の依存なし
- ファイルを開くときは必ず `encoding="utf-8"` を付ける
- `~/.claude/` の中身は、`restore` と `repair --in-place` 以外では書き換えない
