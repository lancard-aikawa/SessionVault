# SessionVault 設計

2026-10-01 時点の案。実装しながら直す。

## 1. 守る対象

`~/.claude/projects/<project-dir>/` の下にあるもの。

| パス | 中身 | 対象 |
|---|---|---|
| `<session-id>.jsonl` | セッション本体 | ○ |
| `<session-id>/subagents/agent-*.jsonl` | サブエージェントの会話 | ○ |
| `<session-id>/subagents/agent-*.meta.json` | サブエージェントの付帯情報 | ○ |
| `<session-id>/tool-results/*` | 長いツール結果を外に出したもの | ○ |
| `<session-id>/auto-mode-classifier-error.txt` など | 診断用の出力 | × |
| `memory/*.md` | 自動メモリ | ○（§1.1） |

`<project-dir>` は作業フォルダのパスを `C--work-claude` のように変換した名前。Claude Code が決めるので、そのまま使う。
ただし**大文字・小文字が揺れる**（同じプロジェクトでセッションは `C--Repos-example-app`、memory は `c--Repos-example-app` にあった）。
Windows では同じフォルダなので、プロジェクトを突き合わせるときは大文字・小文字を無視して比べる。保管庫の中では元の綴りのまま置く。

### 1.1 memory の扱い

memory はセッションと違って追記ではなく、書き換え・削除される。そのため、セッション以上に世代を残す意味がある。
規則は §3 と同じで、中身が変わったら前の版を世代に入れる（「先頭が一致すれば上書き」は使わず、変わったら必ず世代に入れる）。

memory の各ファイルには、どの会話から生まれたかが書かれていない。ただし、セッションの記録には memory への書き込みが残っている
（2026-10-01 の実測: 36 セッションに Write 59 件・Edit 59 件。`tool_use` の `input.file_path` が `...\memory\*.md`）。
これを拾えば、**memory を会話の索引として使える**。「この覚え書きはいつ、どの会話で書かれ、何度直されたか」を引ける。

- `sessionvault memory-index` で、memory ファイルごとに `[(session-id, timestamp, Write|Edit)]` の一覧を作り、`<vault>/index/memory.json` に書く
- 消えた memory も、世代とこの索引から「いつ、どの会話で消したか」まで辿れる
- Viewer は、この索引を使って memory からセッションへ飛べる（Viewer 側の作業）
- 優先度は backup / verify より後。backup が memory を世代付きで残していれば、索引は後からいつでも作り直せる

### セッション JSONL の中身（2026-10-01 の実測）

333 ファイル・124,566 行を読んだ結果。JSON として読めない行は 0、`parentUuid` が同じファイル内に無い行も 0。

- 1 行 1 レコード。主なキーは `type` `uuid` `parentUuid` `sessionId` `timestamp` `cwd` `version` `message`
- `type` は `assistant` `user` `attachment` `system` のほか、`ai-title` `last-prompt` `file-history-snapshot` `queue-operation` など 18 種類。
  知らない `type` が来ても捨てずにそのまま扱う（Claude Code の版で増える）
- 基本は追記だけでファイルが伸びる。大きいものは 20 MB を超える

## 2. 保管庫の形式

```
<vault>/
  vault.json                         形式の版、元の場所、作成日時
  mirror/<project-dir>/...           最新の「正しい」版。~/.claude/projects と同じ木の形
  generations/<project-dir>/<relpath>@<YYYYMMDDTHHMMSSZ>
                                     mirror から押し出された前の版。同じ秒に 2 回押し出したら末尾に -1, -2 …
  log/<YYYY-MM>.jsonl                backup / prune / repair / restore の記録（1 行 1 件）
  index/memory.json                  memory と、それを書いたセッションの対応（§1.1）
  index/src-missing.json             元から消えたと気づいたもの {"<project-dir>/<relpath>": 気づいた時刻}
```

- 世代は名前に `@時刻` が付くので、パスが Windows の 260 文字を超えやすい（2026-10-01 に tool-results の長い名前で実際に失敗した）。
  保管庫のパスは `\\?\` を付けた形で扱う（`vault.long_path`）

### 2.1 保管庫の場所と設定ファイル

保管庫は既定で**プログラムの置き場所の下**に作る。

| 起動のしかた | プログラムの置き場所（`<app>`） |
|---|---|
| exe（PyInstaller） | exe のあるフォルダ |
| `uv run sessionvault`（リポジトリから） | リポジトリのルート |

- 設定ファイルは `<app>/sessionvault.json`。無ければ既定値で動く
- 保管庫の場所は、`--vault` → 環境変数 `SESSIONVAULT_DIR` → 設定ファイルの `vault` → `<app>/vault` の順で決まる
- 設定は手で書いても、`sessionvault config set <key> <value>` で変えてもよい。Claude に「保管庫を F: に移して」と頼めば、このコマンドで変えられる
- 設定ファイルの場所は `--config` で変えられる。Viewer のように別のアプリから読み込むときは、`<app>` が決まらないので `--config` に当たる引数を必ず渡す
- 設定ファイルには手元のパスが入るので git に入れない。見本は `sessionvault.sample.json`
- 保管庫の場所を変えても、中身は自動では移さない（`config set vault` は「前の場所に保管庫が残っている」と表示するだけ）

```json
{
  "vault": "F:/Backup/SessionVault",
  "include_memory": true,
  "retention": {
    "max_generations": 20,
    "max_age_days": 365,
    "min_keep": 3
  }
}
```

- `mirror/` を元と同じ木の形にしておくと、Viewer は今の `archive_dir/projects` を読むのと同じ処理で読める
- `vault.json` の `format` は整数。形式を変えたら上げて、古い保管庫を移す処理を書く
- 時刻は UTC。ファイル名に `:` は使えないので基本形式で書く

## 3. backup の規則

ファイルごとに、元 (`src`) と `mirror` を比べて次のどれかにする。

| 状況 | 処理 | ログの種類 |
|---|---|---|
| mirror に無い | コピー | `new` |
| サイズと更新時刻が同じ | 何もしない | — |
| src の方が長く、mirror の中身が src の先頭と一致する | mirror を上書き | `grow` |
| src の方が短い、または先頭が一致しない | mirror を generations へ移してからコピー | `diverge` |
| （JSONL 以外）中身が変わった | mirror を generations へ移してからコピー | `change` |
| サイズか更新時刻が違うが、中身は同じ | mirror の更新時刻だけ合わせる | — |
| src が消えた | 何もしない（mirror は残す） | `src-missing`（初回だけ。`index/src-missing.json` で覚える） |

- `grow` を使うのは追記で伸びる `*.jsonl` だけ。memory・`*.meta.json`・tool-results は、変わったら必ず世代に入れる（`change`）
- 「先頭が一致する」は、src を丸ごと読んで mirror のバイト列と比べる。2026-10-01 の実測で、初回（766 件・865 MB）が 2.8 秒、変更なしの 2 回目が 0.1 秒台なので、ハッシュや末尾だけの比較にはしていない
- コピーは一時ファイルに書いてから `os.replace` で置き換える（書きかけを残さない）。全部写せたときだけ mirror の更新時刻を src に合わせる
- Claude Code が書いている最中のファイルを読むと、最後の行が途中で切れていることがある。最後の行が改行で終わっていなければ、その行を除いた長さまでをコピーする。改行で終わる行が 1 つも無ければ写さない
- 保管庫に同じプロジェクトが別の綴り（`C--` と `c--`）で既にあれば、そちらへ入れる
- 読めないファイルがあっても止めずに残りを写し、最後に一覧を出して終了コード 1
### 3.1 世代の間引き

設定の `retention` で決める。backup の最後に実行し、`sessionvault prune` で単独でも実行できる（`--dry-run` で消すものを表示するだけ）。

| キー | 意味 | 既定 |
|---|---|---|
| `max_generations` | 1 ファイルあたり残す世代の数。超えたら古いものから消す | `null`（無制限） |
| `max_age_days` | これより古い世代を消す | `null`（無制限） |
| `min_keep` | 上の 2 つに当てはまっても、新しいものからこの数は残す | `3` |

- 既定はどちらも無制限で、何も消さない。消すのは設定したときだけ
- 間引くのは `generations/` だけ。`mirror/` は、元のファイルが消えていても消さない
- 消したものは `log/` に記録する

## 4. verify の検査項目

| 検査 | 重さ | 説明 |
|---|---|---|
| `bad-json` | エラー | JSON として読めない行。最後の行だけなら `truncated-tail` として区別する |
| `no-newline` | 警告 | ファイルが改行で終わっていない |
| `dangling-parent` | エラー | `parentUuid` が同じファイル（とサブエージェント）のどの `uuid` にも無い |
| `duplicate-uuid` | 警告 | 同じ `uuid` が 2 回以上ある |
| `diverged` | エラー | src が mirror より短い、または先頭が一致しない（backup 前の検出） |
| `src-missing` | 情報 | mirror にはあるが src に無い（自動削除か手で消したもの） |

- 終了コード: 0 = 問題なし、1 = エラーあり、2 = 引数の誤り
- `--json` で、1 件 1 オブジェクトの配列 `{session, project, path, check, severity, line, detail}` を出す。RepoTether はこれを読む

## 5. repair と restore

- **repair** は既定で `--out` に直した版を書くだけ。`~/.claude/` は触らない
  - `truncated-tail`: 最後の壊れた行を落とす
  - `bad-json`（途中の行）: その行を落とし、子の `parentUuid` を落とした行の親につなぎ直す
  - `diverged`: mirror の版と src の版の、長い方の先頭が一致している部分を取る（どちらを採るかは表示して選ばせる）
- `--in-place` を付けたときだけ元のファイルを置き換える。置き換える前に必ず backup を取る
- **restore** は mirror（または `--generation` で指定した世代）を元の場所へ書き戻す。元にファイルがあれば、上書き前にそれを世代として保管庫へ入れる
- repair と restore は、対象のセッションを Claude Code で開いていないときに使う。開いているかは判定できないので、実行前に注意を表示する

## 6. 他のアプリとのつなぎ方

| 相手 | つなぎ方 |
|---|---|
| Claude History Viewer | `sessionvault` をパッケージとして読み込み、`archive.py` の代わりに `backup.run()` を呼ぶ。設定ファイルの場所は Viewer が渡す。読み込み元は `mirror/` |
| RepoTether | `sessionvault.exe verify --json` を呼んで結果を表示する。書き込む操作は呼ばない（RepoTether は読むだけの方針） |
| 定期実行 | タスクスケジューラで `sessionvault backup` を 30 分ごと。Claude Code の `SessionEnd` フックから呼ぶ案もある |

### Viewer の既存のバックアップからの移行

Viewer は `~/.claude/chat-viewer-archive/projects/`（`archive_dir` が空のとき）に同じ木の形でコピーしている。
`sessionvault import <dir>` で、その中身を `mirror/` に取り込む（mirror に無いものだけ。食い違えば世代に入れる）。

## 7. 決めていないこと

- exe にするときの配布の仕方（PkgUpdater と同じ PyInstaller で足りるか）
- プロジェクト直下の `sessions-index.json`（2026-10-01 に 2 件だけあった）を守る対象に入れるか。今は入れていない
- memory の索引を Viewer でどう見せるか

### 決めたこと（2026-10-01）

- memory も守る。世代付きで残し、セッションの記録から「どの会話で書いたか」の索引を作る（§1.1）
- 保管庫の既定はプログラムの置き場所の下。設定ファイルか `config set` で変える（§2.1）
- 世代の間引きは設定で決める。既定は消さない（§3.1）
