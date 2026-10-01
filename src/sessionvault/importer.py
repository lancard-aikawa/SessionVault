"""import: 他のバックアップ（Viewer の archive など）を保管庫へ取り込む。docs/design.md §6"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .backup import iter_targets
from .vault import Vault, long_path, project_child, utc_now, write_bytes_atomic


@dataclass
class Imported:
    counts: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)   # [(project, rel, message)]

    def add(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1


def run(other: Path, src: Path, vault_root: Path, now: datetime | None = None) -> Imported:
    """mirror に無いものは mirror へ。JSONL で mirror の続きなら mirror を伸ばし、mirror の先頭部分なら何もしない。
    それ以外で中身が違えば、取り込む側を世代に入れる（mirror は変えない）"""
    now = now or utc_now()
    vault = Vault(vault_root)
    vault.ensure(src)
    result = Imported()
    for t in iter_targets(long_path(other)):
        mproject = project_child(vault.mirror, t.project).name
        dest = vault.mirror / mproject / t.rel
        try:
            data = t.path.read_bytes()
            old = dest.read_bytes() if dest.is_file() else None
            if old is None:
                write_bytes_atomic(dest, data)
                kind, gen = "new", None
            elif old == data:
                result.add("same")
                continue
            elif t.append and old.startswith(data):
                result.add("older")  # mirror の先頭部分。失うものは無い
                continue
            elif t.append and data.startswith(old):
                write_bytes_atomic(dest, data)
                kind, gen = "grow", None
            else:
                kind, gen = "generation", vault.stash(mproject, t.rel, data, now)
        except OSError as e:
            result.errors.append((t.project, t.rel, str(e)))
            continue
        result.add(kind)
        entry = {"op": "import", "kind": kind, "project": mproject, "path": t.rel, "size": len(data),
                 "from": str(other)}
        if gen:
            entry["generation"] = gen.relative_to(vault.root).as_posix()
        vault.log(now, **entry)
    return result
