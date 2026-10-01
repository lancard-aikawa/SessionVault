"""元の場所と保管庫の場所を決める"""
import os
import re
import sys
from pathlib import Path

ENV_VAULT = "SESSIONVAULT_DIR"
CONFIG_NAME = "sessionvault.json"


def claude_projects_dir() -> Path:
    """Claude Code がセッションを書く場所"""
    return Path.home() / ".claude" / "projects"


def project_dir_name(folder: str) -> str:
    """作業フォルダのパスを、Claude Code が ~/.claude/projects の下に作る名前にする。
    英数字以外はすべて - になる（C:\\Repos\\x → C--Repos-x。2026-10-01 に実データ 24 件で確認）。
    大文字・小文字は揺れるので、突き合わせは casefold で行う"""
    return re.sub(r"[^A-Za-z0-9]", "-", folder)


def as_project_dir(value: str) -> str:
    """プロジェクト名か作業フォルダのパスを受け取り、プロジェクト名にする"""
    return project_dir_name(value) if any(c in value for c in ":\\/") else value


def app_dir() -> Path:
    """プログラムの置き場所。exe ならそのフォルダ、リポジトリからならリポジトリのルート"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    return app_dir() / CONFIG_NAME


def vault_dir(cli_value: str | None = None, config_value: str | None = None) -> Path:
    """保管庫の場所。--vault、環境変数、設定ファイル、既定値の順で決まる"""
    for v in (cli_value, os.environ.get(ENV_VAULT), config_value):
        if v:
            return Path(v).expanduser()
    return app_dir() / "vault"
