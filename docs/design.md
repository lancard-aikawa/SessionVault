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
| `sessions-index.json` | 古い版の Claude Code が書いた索引（要約と最初の依頼文）。2026-10-01 に 2026 年 1〜2 月のものが 2 件 | ○（変わったら世代に入れる） |

`<project-dir>` は作業フォルダのパスを `C--work-claude` のように変換した名前。Claude Code が決めるので、そのまま使う。
ただし**大文字・小文字が揺れる**（同じプロジェクトでセッションは `C--Repos-example-app`、memory は `c--Repos-example-app` にあった）。
Windows では同じフォルダなので、プロジェクトを突き合わせるときは大文字・小文字を無視して比べる。保管庫の中では元の綴りのまま置く。

### 1.1 memory の扱い

memory はセッションと違って追記ではなく、書き換え・削除される。そのため、セッション以上に世代を残す意味がある。
規則は §3 と同じで、中身が変わったら前の版を世代に入れる（「先頭が一致すれば上書き」は使わず、変わったら必ず世代に入れる）。

memory の各ファイルには、どの会話から生まれたかが書かれていない。ただし、セッションの記録には memory への書き込みが残っている
（2026-10-01 の実測: 36 セッションに Write 59 件・Edit 59 件。`tool_use` の `input.file_path` が `...\memory\*.md`）。
これを拾えば、**memory を会話の索引として使える**。「この覚え書きはいつ、どの会話で書かれ、何度直されたか」を引ける。

- `sessionvault memory-index` で、memory ファイルごとに書き込みの一覧を作り、`<vault>/index/memory.json` に書く

  ```json
  {"generated": "2026-10-01T02:29:00+00:00",
   "memory": {"C--work-claude/memory/MEMORY.md": {
     "exists": true,
     "writes": [{"session": "…", "project": "C--work-claude", "subagent": false,
                 "timestamp": "2026-09-08T09:49:40.747Z", "tool": "Edit", "ok": true}]}}}
  ```

  - 拾うのは `Write` `Edit` `MultiEdit` の `tool_use` で、`input.file_path` が `…\.claude\projects\<project-dir>\memory\<name>.md` のもの。`Read` は数えない
  - `ok` は、対応する `tool_result` が `is_error: true` なら false
  - mirror と src の両方を読み、同じ `tool_use` の id は 1 回だけ数える（src から消えたセッションも mirror に残っている）
  - キーの `<project-dir>` は、今ある memory フォルダの綴りに寄せる（パスには `c--`、フォルダは `C--` ということがある）
  - `exists` は今の src にその memory があるか
  - 2026-10-01 の実測: memory 56 件・書き込み 120 件・消えたもの 4 件、4.4 秒
- 消えた memory も、世代とこの索引から「どの会話で書いたか」までは辿れる。Bash の `rm` などで消した記録は、コマンドの文字列から確実には拾えないので索引に入れていない
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
  lock                               書き込むあいだ持つロック（§2.2）
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

### 2.2 同時に動かしたとき

定期実行と手動の実行、Viewer からの呼び出しが重なることがある。保管庫に書く処理（backup・prune・import・memory-index・restore・`repair --in-place`）は、
`<vault>/lock` に OS のファイルロック（Windows は `msvcrt.locking`、ほかは `flock`）を取ってから動く。

- 取れなければ待たずに `VaultLocked` で止まる。CLI は終了コード 1。次の定期実行で取り直せばよいので、待ち合わせはしない
- プロセスが落ちれば OS がロックを外すので、取り残されて動かなくなることはない（ファイルが残っていても中身は見ない）
- 同じプロセスの中では入れ子で取れる（`repair --in-place` が backup を呼ぶ）
- verify と `restore --list`・`prune --dry-run` は読むだけなのでロックを取らない。backup の途中に読んでも、ファイルは `os.replace` で置き換わるので書きかけは見えない
- 2026-10-01 に 2 つのプロセスで同時に backup を走らせ、後の方が止まり、先の方が最後まで写すことを確かめた

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
- 別の sessionvault が保管庫を使っていれば、待たずに終了コード 1 で止まる（§2.2）
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
| `bad-json` | エラー | JSON として読めない行（UTF-8 として読めない行も含む） |
| `truncated-tail` | 警告 | 最後の行が JSON として読めず、改行でも終わっていない。Claude Code が書いている最中にも起きる |
| `no-newline` | 警告 | ファイルが改行で終わっていない（最後の行は読める）。`truncated-tail` と重ねては出さない |
| `dangling-parent` | エラー | `parentUuid` が同じセッション（本体とサブエージェント）のどの `uuid` にも無い |
| `duplicate-uuid` | 警告 | 同じファイルに同じ `uuid` が 2 回以上ある |
| `diverged` | エラー | src が mirror より短い、または先頭が一致しない（backup 前の検出）。書きかけの最後の行は数えない |
| `src-missing` | 情報 | mirror にはあるが src に無い（自動削除か手で消したもの） |
| `unreadable` | エラー | ファイルを開けない |

- 検査するのは JSONL（セッション本体とサブエージェント）だけ。memory・meta・tool-results は中身の形を検査しない（`src-missing` だけ見る）
- 保管庫が無ければ、保管庫を使う検査（`diverged` `src-missing`）は飛ばす。verify は保管庫にも何も書かない
- 終了コード: 0 = エラーなし（警告・情報だけなら 0）、1 = エラーあり、2 = 引数の誤り
- `--json` で、1 件 1 オブジェクトの配列 `{session, project, path, check, severity, line, detail}` を出す。RepoTether はこれを読む。
  コンソールの文字コード（日本語の Windows では cp932）に左右されないよう、日本語は `\uXXXX` にして ASCII だけで出す
- 並びはエラー → 警告 → 情報、その中はプロジェクト・パス・行の順

2026-10-01 の実測（408 ファイル・815 MB・14 万行）: 4.7 秒（ディスクキャッシュに乗っていないと 21 秒）。ほとんどが JSON の解析。
出たのは `duplicate-uuid` 3 件だけで、どれも同じ uuid・親・時刻の tool_result が約 1,200 行後にもう一度書かれたもの（行のバイト列は同一ではない）。
Claude Code の書き直しとみて警告のままにする。

## 5. repair と restore

- **repair** は既定で `--out` に直した版を書くだけ。`~/.claude/` は触らない。対象はセッション本体の JSONL だけ
  - `truncated-tail`: 最後の壊れた行を落とす
  - `no-newline`: 最後に改行を足す
  - `bad-json`（途中の行）: その行を落とし、子の `parentUuid` を落とした行の親につなぎ直す
    - 壊れた行の uuid と親は正規表現で拾う。ただし Claude Code の行は `parentUuid` が先頭、`uuid` が後ろの方にあるので、
      後半が欠けた行は uuid が読めない（2026-10-01 に実データで確認）。そのときは、その行より後で初めて出てくる
      「行き先の無い parentUuid」をその行の uuid だったとみなす。同じセッションのサブエージェントにある uuid は行き先ありとみなす
    - 落とした行が続いていれば、親を辿って最初の生きている行（または null）につなぐ
  - 手を入れた行だけを `JSON.stringify` と同じ詰めた形（`ensure_ascii=False`、区切りに空白なし）で書き直す。ほかの行はバイト列のまま
  - `diverged` はまだ直さない（mirror と src のどちらを採るかを選ばせる形が決まっていない）。今は restore で選んだ版に戻す
- `--in-place` を付けたときだけ元のファイルを置き換える。置き換える前に backup を取り、さらに元のバイト列をそのまま世代に入れる
  （backup は書きかけの最後の行を写さないので、それだけでは元が完全には残らない）。backup に失敗したら置き換えない
  - backup が壊れた版を mirror に入れるので、**壊れる前の版は世代の側**にある。戻すときは `restore --list` で見て `--generation` で選ぶ
- **restore** は mirror（または `--generation` で指定した世代）を元の場所へ書き戻す。元にファイルがあれば、上書き前にそれを世代として保管庫へ入れる
  - mirror から戻すときは本体とサブエージェント・tool-results をまとめて戻す。世代から戻すのは本体だけ
  - `--list` で戻せる版（世代の名前とバイト数、最後が mirror）を出す。中身が同じファイルは書かない
- repair と restore は、対象のセッションを Claude Code で開いていないときに使う。開いているかは判定できないので、実行前に注意を表示する

## 6. 他のアプリとのつなぎ方

| 相手 | つなぎ方 |
|---|---|
| Claude History Viewer | `sessionvault` をパッケージとして読み込み、`archive.py` の代わりに `backup.run()` を呼ぶ。設定ファイルの場所は Viewer が渡す。読み込み元は `mirror/` |
| RepoTether | `sessionvault.exe verify --json` を呼んで結果を表示する。書き込む操作は呼ばない（RepoTether は読むだけの方針） |
| 定期実行 | タスクスケジューラで `sessionvault backup` を 30 分ごととログオン時（`scripts/register-task.ps1`）。`.venv/Scripts/pythonw.exe -m sessionvault backup` で窓を出さない。`SessionEnd` フックは使っていない |

### Viewer の既存のバックアップからの移行

Viewer は `~/.claude/chat-viewer-archive/projects/`（`archive_dir` が空のとき）に同じ木の形でコピーしている。
`sessionvault import <dir>` で、その中身を保管庫に取り込む。`~/.claude/` も取り込み元も書き換えない。

| 状況 | 処理 | ログの種類 |
|---|---|---|
| mirror に無い | mirror へコピー | `new` |
| 中身が同じ | 何もしない | —（数だけ `same`） |
| JSONL で、取り込む側が mirror の先頭部分 | 何もしない（失うものが無い） | —（数だけ `older`） |
| JSONL で、取り込む側が mirror の続きまである | mirror を上書き | `grow` |
| それ以外で中身が違う | 取り込む側を世代に入れる。mirror は変えない | `generation` |

2026-10-01 に Viewer の archive（334 ファイル）で試した結果: same 331、grow 3、食い違い 0。

## 7. 決めていないこと

- exe にするときの配布の仕方（PkgUpdater と同じ PyInstaller で足りるか）
- memory の索引を Viewer でどう見せるか

### 決めたこと（2026-10-01）

- memory も守る。世代付きで残し、セッションの記録から「どの会話で書いたか」の索引を作る（§1.1）
- 保管庫の既定はプログラムの置き場所の下。設定ファイルか `config set` で変える（§2.1）
- 世代の間引きは設定で決める。既定は消さない（§3.1）
