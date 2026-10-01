"""コマンドライン。サブコマンドの中身は docs/design.md に沿って順に書く"""
import argparse
import sys
from pathlib import Path

from . import __version__
from .paths import claude_projects_dir, vault_dir

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sessionvault", description="Claude Code のセッション履歴を残し、検査し、直す")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--vault", help="保管庫の場所（既定: $SESSIONVAULT_DIR か ~/.sessionvault）")
    p.add_argument("--src", help="元の場所（既定: ~/.claude/projects）")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("backup", help="セッションを保管庫へコピーする")

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

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    src = Path(args.src) if args.src else claude_projects_dir()
    vault = vault_dir(args.vault)
    print(f"{args.command}: 未実装です（src={src}, vault={vault}）", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
