"""元の場所と保管庫の場所を決める"""
import os
import sys
from pathlib import Path

ENV_VAULT = "SESSIONVAULT_DIR"
CONFIG_NAME = "sessionvault.json"


def claude_projects_dir() -> Path:
    """Claude Code がセッションを書く場所"""
    return Path.home() / ".claude" / "projects"


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
