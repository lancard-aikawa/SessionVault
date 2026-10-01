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
| `memory/` | 自動メモリ | 未定（§7） |

`<project-dir>` は作業フォルダのパスを `C--work-claude` のように変換した名前。Claude Code が決めるので、そのまま使う。

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
                                     mirror から押し出された前の版
  log/<YYYY-MM>.jsonl                backup / repair / restore の記録（1 行 1 件）
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
| src が消えた | 何もしない（mirror は残す） | `src-missing`（初回だけ） |

- 「先頭が一致する」は、mirror の長さ分だけ src を読んでハッシュを比べる。20 MB で数十 ms なので最初は素直に全部比べ、遅ければ末尾の数十 KB だけに減らす
- コピーは一時ファイルに書いてから `os.replace` で置き換える（書きかけを残さない）
- Claude Code が書いている最中のファイルを読むと、最後の行が途中で切れていることがある。最後の行が改行で終わっていなければ、その行を除いた長さまでをコピーする
- 世代はいまのところ消さない。容量が問題になったら、世代の数か日数で間引く設定を足す

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
| Claude History Viewer | `sessionvault` をパッケージとして読み込み、`archive.py` の代わりに `backup.run()` を呼ぶ。読み込み元は `mirror/` |
| RepoTether | `sessionvault.exe verify --json` を呼んで結果を表示する。書き込む操作は呼ばない（RepoTether は読むだけの方針） |
| 定期実行 | タスクスケジューラで `sessionvault backup` を 30 分ごと。Claude Code の `SessionEnd` フックから呼ぶ案もある |

### Viewer の既存のバックアップからの移行

Viewer は `~/.claude/chat-viewer-archive/projects/`（`archive_dir` が空のとき）に同じ木の形でコピーしている。
`sessionvault import <dir>` で、その中身を `mirror/` に取り込む（mirror に無いものだけ。食い違えば世代に入れる）。

## 7. 決めていないこと

- `memory/` も守るか（セッションではないが、消えると困る）
- 保管庫を別ドライブ（F:）に置くのを既定にするか
- 世代の間引き方
- exe にするときの配布の仕方（PkgUpdater と同じ PyInstaller で足りるか）
