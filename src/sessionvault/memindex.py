"""memory-index: memory ファイルごとに、それを書いたセッションの一覧を作る。docs/design.md §1.1"""
import json
import re
from datetime import datetime
from pathlib import Path

from .backup import iter_targets
from .vault import Vault, long_path, project_child, utc_now, write_json

TOOLS = ("Write", "Edit", "MultiEdit")
# ...\.claude\projects\<project-dir>\memory\<name>.md
_MEMORY_PATH = re.compile(r"[\\/]\.claude[\\/]projects[\\/]([^\\/]+)[\\/]memory[\\/]([^\\/]+\.md)$", re.I)


def _session_files(root: Path):
    """root の下のセッション JSONL（本体とサブエージェント）。(プロジェクト, 相対パス, パス)"""
    for t in iter_targets(root, include_memory=False):
        if t.append:
            yield t.project, t.rel, t.path


def _scan(data: bytes, project: str, rel: str, writes: dict, errors: set) -> None:
    for raw in data.split(b"\n"):
        # 全部を JSON として読むと遅いので、関係しそうな行だけ読む
        has_use = b'"tool_use"' in raw and b"memory" in raw
        has_err = b'"is_error":true' in raw
        if not (has_use or has_err):
            continue
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_result" and c.get("is_error") is True:
                errors.add(c.get("tool_use_id"))
            if c.get("type") != "tool_use" or c.get("name") not in TOOLS:
                continue
            fp = (c.get("input") or {}).get("file_path")
            m = _MEMORY_PATH.search(fp) if isinstance(fp, str) else None
            if not m or c.get("id") in writes:
                continue
            writes[c.get("id")] = {
                "memory_project": m.group(1), "name": m.group(2),
                "session": rec.get("sessionId"), "project": project,
                "subagent": "/subagents/" in rel, "timestamp": rec.get("timestamp"), "tool": c.get("name"),
            }


def build(src: Path, vault_root: Path | None, now: datetime | None = None) -> dict:
    """mirror と src の両方を読む（src から消えたセッションも mirror には残っている）。同じ tool_use は 1 回だけ数える"""
    now = now or utc_now()
    src = long_path(src)
    vault = Vault(vault_root) if vault_root else None
    writes: dict = {}
    errors: set = set()
    roots = ([vault.mirror] if vault and vault.mirror.is_dir() else []) + [src]
    for root in roots:
        for project, rel, path in _session_files(root):
            _scan(path.read_bytes(), project, rel, writes, errors)

    memory: dict = {}
    for tool_id, w in writes.items():
        # <project-dir> は大文字・小文字が揺れるので、今ある memory フォルダの綴りに寄せる
        proj = project_child(src, w["memory_project"]).name
        key = f"{proj}/memory/{w['name']}"
        entry = memory.setdefault(key, {"exists": (src / proj / "memory" / w["name"]).is_file(), "writes": []})
        entry["writes"].append({
            "session": w["session"], "project": w["project"], "subagent": w["subagent"],
            "timestamp": w["timestamp"], "tool": w["tool"], "ok": tool_id not in errors,
        })
    for entry in memory.values():
        entry["writes"].sort(key=lambda x: x["timestamp"] or "")
    return {"generated": now.isoformat(timespec="seconds"), "memory": dict(sorted(memory.items()))}


def run(src: Path, vault_root: Path, now: datetime | None = None) -> tuple[dict, Path]:
    vault = Vault(vault_root)
    vault.ensure(src)
    index = build(src, vault_root, now)
    path = vault.index_dir / "memory.json"
    write_json(path, index)
    return index, path
