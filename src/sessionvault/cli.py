"""コマンドライン。サブコマンドの中身は docs/design.md に沿って順に書く"""
import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import config as cfgmod
from .paths import claude_projects_dir, default_config_path, vault_dir

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sessionvault", description="Claude Code のセッション履歴を残し、検査し、直す")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", help="設定ファイル（既定: プログラムの置き場所の sessionvault.json）")
    p.add_argument("--vault", help="保管庫の場所（設定より優先）")
    p.add_argument("--src", help="元の場所（既定: ~/.claude/projects）")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("backup", help="セッションと memory を保管庫へコピーする")

    v = sub.add_parser("verify", help="元と保管庫を検査する")
    v.add_argument("session", nargs="?", help="セッション ID（省略時はすべて）")
    v.add_argument("--json", action="store_true", help="結果を JSON で出す")

    r = sub.add_parser("repair", help="壊れたセッションを直した版を書き出す")
    r.add_argument("session", help="セッション ID")
    out = r.add_mutually_exclusive_group(required=True)
    out.add_argument("--out", help="直した版の書き出し先")
    out.add_argument("--in-place", action="store_true", help="元のファイルを置き換える（先に backup を取る）")

    s = sub.add_parser("restore", help="保管庫から元の場所へ戻す")
    s.add_argument("session", help="セッション ID")
    s.add_argument("--generation", help="戻す世代（省略時は mirror）")

    i = sub.add_parser("import", help="他のバックアップ（Viewer の archive など）を保管庫へ取り込む")
    i.add_argument("dir", help="projects と同じ木の形のフォルダ")

    pr = sub.add_parser("prune", help="設定の retention に従って古い世代を消す")
    pr.add_argument("--dry-run", action="store_true", help="消すものを表示するだけ")

    sub.add_parser("memory-index", help="memory とそれを書いたセッションの対応表を作る")

    c = sub.add_parser("config", help="設定を見る・変える")
    csub = c.add_subparsers(dest="config_command", required=True)
    csub.add_parser("show", help="今の設定（既定値込み）と、実際に使う保管庫の場所を表示する")
    csub.add_parser("path", help="設定ファイルの場所を表示する")
    cs = csub.add_parser("set", help="設定を 1 つ変える")
    cs.add_argument("key", choices=cfgmod.keys())
    cs.add_argument("value", help="null で無制限・既定に戻す")

    return p


def _cmd_config(args, config_path: Path, cfg: dict) -> int:
    if args.config_command == "path":
        print(config_path)
        return EXIT_OK
    if args.config_command == "show":
        shown = dict(cfg)
        shown["_effective_vault"] = str(vault_dir(args.vault, cfg["vault"]))
        shown["_config_file"] = str(config_path) + ("" if config_path.is_file() else "（まだ無い）")
        print(json.dumps(shown, ensure_ascii=False, indent=2))
        return EXIT_OK
    # set
    old_vault = vault_dir(None, cfg["vault"])
    try:
        new_cfg = cfgmod.set_value(cfg, args.key, args.value)
    except ValueError as e:
        print(f"値が読めません: {e}", file=sys.stderr)
        return EXIT_USAGE
    cfgmod.save(config_path, new_cfg)
    print(f"{args.key} = {json.dumps(cfgmod.get(new_cfg, args.key), ensure_ascii=False)}（{config_path}）")
    if args.key == "vault":
        new_vault = vault_dir(None, new_cfg["vault"])
        if new_vault != old_vault and old_vault.is_dir() and any(old_vault.iterdir()):
            print(f"注意: 前の保管庫 {old_vault} に中身が残っています。自動では移しません。", file=sys.stderr)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config) if args.config else default_config_path()
    try:
        cfg = cfgmod.load(config_path)
    except (OSError, ValueError) as e:
        print(f"設定ファイルを読めません: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "config":
        return _cmd_config(args, config_path, cfg)

    src = Path(args.src) if args.src else claude_projects_dir()
    vault = vault_dir(args.vault, cfg["vault"])
    print(f"{args.command}: 未実装です（src={src}, vault={vault}）", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
