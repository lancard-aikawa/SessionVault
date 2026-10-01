"""元の場所と保管庫の場所を決める"""
import os
from pathlib import Path

ENV_VAULT = "SESSIONVAULT_DIR"


def claude_projects_dir() -> Path:
    """Claude Code がセッションを書く場所"""
    return Path.home() / ".claude" / "projects"


def vault_dir(cli_value: str | None = None) -> Path:
    """保管庫の場所。--vault、環境変数、既定値の順で決まる"""
    if cli_value:
        return Path(cli_value).expanduser()
    env = os.environ.get(ENV_VAULT)
    if env:
        return Path(env).expanduser()
    return Path.home() / ".sessionvault"
