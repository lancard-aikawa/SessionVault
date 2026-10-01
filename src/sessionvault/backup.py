"""backup: ~/.claude/projects を保管庫へ写す。規則は docs/design.md §3"""
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import prune
from .vault import Vault, long_path, project_child, read_json, utc_now, write_bytes_atomic, write_json

TMP_SUFFIX = ".sv-tmp"


@dataclass
class Target:
    project: str      # src 側の綴り
    rel: str          # プロジェクトからの相対パス（/ 区切り）
    path: Path
    append: bool      # 追記だけで伸びるファイル（JSONL）か


@dataclass
class Result:
    counts: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)   # [(project, rel, message)]
    pruned: list = field(default_factory=list)

    def add(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1


def iter_targets(src: Path, include_memory: bool = True):
    """守る対象のファイルを列挙する（design.md §1 の表）"""
    if not src.is_dir():
        return
    for project in sorted(p for p in src.iterdir() if p.is_dir()):
        for entry in sorted(project.iterdir()):
            if entry.is_file():
                if entry.suffix == ".jsonl":
                    yield Target(project.name, entry.name, entry, True)
                elif entry.name == "sessions-index.json":  # 古い版の索引。要約と最初の依頼文が入っている
                    yield Target(project.name, entry.name, entry, False)
            elif entry.name == "memory":
                if include_memory:
                    for f in sorted(entry.rglob("*.md")):
                        if f.is_file():
                            yield Target(project.name, f.relative_to(project).as_posix(), f, False)
            elif entry.is_dir():
                for f in sorted((entry / "subagents").rglob("*")):
                    if f.is_file() and (f.name.endswith(".jsonl") or f.name.endswith(".meta.json")):
                        yield Target(project.name, f.relative_to(project).as_posix(), f, f.suffix == ".jsonl")
                for f in sorted((entry / "tool-results").rglob("*")):
                    if f.is_file():
                        yield Target(project.name, f.relative_to(project).as_posix(), f, False)


def backup_file(vault: Vault, mproject: str, t: Target, now: datetime) -> tuple[str | None, Path | None, int]:
    """1 ファイルを写す。(ログの種類, 押し出した世代, 写した長さ) を返す。何もしなければ種類は None"""
    st = t.path.stat()
    dest = vault.mirror / mproject / t.rel
    old_st = dest.stat() if dest.is_file() else None
    if old_st and old_st.st_size == st.st_size and old_st.st_mtime_ns == st.st_mtime_ns:
        return None, None, st.st_size

    data = t.path.read_bytes()
    full = len(data) == st.st_size
    if t.append:
        # 書いている最中なら最後の行が途中で切れている。改行までで止める
        cut = data.rfind(b"\n") + 1
        if cut < len(data):
            data, full = data[:cut], False

    kind, gen = None, None
    if old_st is None:
        if not data:
            return None, None, 0  # まだ 1 行も書き終わっていない
        write_bytes_atomic(dest, data)
        kind = "new"
    else:
        old = dest.read_bytes()
        if old != data:
            if t.append and len(data) > len(old) and data.startswith(old):
                kind = "grow"
            else:
                gen = vault.push_generation(mproject, t.rel, now)
                kind = "diverge" if t.append else "change"
            write_bytes_atomic(dest, data)
    if full:
        os.utime(dest, ns=(st.st_atime_ns, st.st_mtime_ns))
    return kind, gen, len(data)


def _mirror_files(vault: Vault):
    if not vault.mirror.is_dir():
        return
    for project in vault.mirror.iterdir():
        if project.is_dir():
            for f in project.rglob("*"):
                if f.is_file() and not f.name.endswith(TMP_SUFFIX):
                    yield project.name, f.relative_to(project).as_posix()


def run(src: Path, vault_root: Path, cfg: dict, now: datetime | None = None) -> Result:
    """保管庫のロックを取ってから実行する"""
    with Vault(vault_root).lock():
        return _run(src, vault_root, cfg, now)


def _run(src: Path, vault_root: Path, cfg: dict, now: datetime | None = None) -> Result:
    now = now or utc_now()
    src = long_path(src)
    vault = Vault(vault_root)
    vault.ensure(src)
    include_memory = cfg.get("include_memory", True)
    result = Result()
    seen: set[tuple[str, str]] = set()
    mproject_of: dict[str, str] = {}

    for t in iter_targets(src, include_memory):
        if t.project not in mproject_of:
            # 保管庫に別の綴り（C-- と c--）で既にあれば、そちらへ入れる
            mproject_of[t.project] = project_child(vault.mirror, t.project).name
        mproject = mproject_of[t.project]
        seen.add((mproject.casefold(), t.rel.casefold()))
        try:
            kind, gen, size = backup_file(vault, mproject, t, now)
        except OSError as e:
            result.errors.append((t.project, t.rel, str(e)))
            continue
        if kind:
            result.add(kind)
            entry = {"op": "backup", "kind": kind, "project": mproject, "path": t.rel, "size": size}
            if gen:
                entry["generation"] = gen.relative_to(vault.root).as_posix()
            vault.log(now, **entry)

    # 元から消えたもの。mirror は消さず、初めて気づいたときだけ記録する
    missing_path = vault.index_dir / "src-missing.json"
    known = read_json(missing_path, {})
    current = {}
    for mproject, rel in _mirror_files(vault):
        if (mproject.casefold(), rel.casefold()) in seen:
            continue
        if not include_memory and rel.startswith("memory/"):
            continue
        key = f"{mproject}/{rel}"
        current[key] = known.get(key, now.isoformat(timespec="seconds"))
        if key not in known:
            result.add("src-missing")
            vault.log(now, op="backup", kind="src-missing", project=mproject, path=rel)
    if current != known:
        write_json(missing_path, current)

    result.pruned = prune.run(vault, cfg.get("retention", {}), now)
    return result
