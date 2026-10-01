"""restore: 保管庫から元の場所へ戻す。規則は docs/design.md §5"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .vault import Vault, find_session, long_path, project_child, utc_now, write_bytes_atomic

CAUTION = "注意: 対象のセッションを Claude Code で開いていないことを確かめてから使ってください（開いているかは判定できません）"


class RestoreError(Exception):
    pass


@dataclass
class Restored:
    rel: str
    action: str             # restored / same
    stashed: Path | None    # 上書き前の元の中身を入れた世代


def locate(vault: Vault, session: str) -> tuple[Path, str]:
    """保管庫の中のセッション。(mirror のプロジェクト, 本体の相対パス)"""
    hits = find_session(vault.mirror, session)
    if not hits:
        raise RestoreError(f"保管庫にセッションがありません: {session}")
    if len(hits) > 1:
        raise RestoreError("複数のプロジェクトに同じセッションがあります: " + ", ".join(h.parent.name for h in hits))
    return hits[0].parent, hits[0].name


def list_versions(vault_root: Path, session: str) -> list[tuple[str, int]]:
    """戻せる版の一覧。[("mirror" か 世代の名前, バイト数)]。古い世代から順に、最後が mirror"""
    vault = Vault(vault_root)
    project, rel = locate(vault, session)
    out = [(name, p.stat().st_size) for name, p in vault.generations_of(project.name, rel)]
    out.append(("mirror", (project / rel).stat().st_size))
    return out


def run(src: Path, vault_root: Path, session: str, generation: str | None = None,
        now: datetime | None = None) -> list[Restored]:
    now = now or utc_now()
    vault = Vault(vault_root)
    project, main_rel = locate(vault, session)

    if generation:
        gens = dict(vault.generations_of(project.name, main_rel))
        if generation not in gens:
            have = ", ".join(gens) or "なし"
            raise RestoreError(f"世代 {generation} がありません（あるもの: {have}）")
        # 世代から戻すのは本体だけ。サブエージェントなどは世代ごとの対応が取れない
        sources = [(main_rel, gens[generation])]
    else:
        sources = [(main_rel, project / main_rel)]
        sub = project / main_rel[: -len(".jsonl")]
        if sub.is_dir():
            sources += sorted((f.relative_to(project).as_posix(), f) for f in sub.rglob("*")
                              if f.is_file() and not f.name.endswith(".sv-tmp"))

    target = project_child(long_path(src), project.name)
    out = []
    for rel, source in sources:
        data = source.read_bytes()
        dest = target / rel
        stashed = None
        if dest.is_file():
            cur = dest.read_bytes()
            if cur == data:
                out.append(Restored(rel, "same", None))
                continue
            stashed = vault.stash(project.name, rel, cur, now)
        write_bytes_atomic(dest, data)
        entry = {"op": "restore", "project": project.name, "path": rel, "size": len(data),
                 "from": source.relative_to(vault.root).as_posix()}
        if stashed:
            entry["stashed"] = stashed.relative_to(vault.root).as_posix()
        vault.log(now, **entry)
        out.append(Restored(rel, "restored", stashed))
    return out
