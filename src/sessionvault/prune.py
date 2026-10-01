"""prune: retention に従って generations/ の古い世代を消す。規則は docs/design.md §3.1"""
from datetime import datetime, timedelta
from pathlib import Path

from .vault import Vault, parse_ts


def _split(name: str) -> tuple[str, datetime, int] | None:
    """a.jsonl@20261001T010203Z-2 → ("a.jsonl", 時刻, 2)。世代の名前でなければ None"""
    base, sep, tail = name.rpartition("@")
    if not sep:
        return None
    stamp, _, n = tail.partition("-")
    when = parse_ts(stamp)
    if when is None or (n and not n.isdigit()):
        return None
    return base, when, int(n or 0)


def plan(vault: Vault, retention: dict, now: datetime) -> list[Path]:
    """消す世代の一覧。retention が既定（どちらも null）なら空"""
    max_gen = retention.get("max_generations")
    max_age = retention.get("max_age_days")
    min_keep = retention.get("min_keep") or 0
    if max_gen is None and max_age is None:
        return []
    if not vault.generations.is_dir():
        return []

    groups: dict[tuple[Path, str], list[tuple[datetime, int, Path]]] = {}
    for f in vault.generations.rglob("*"):
        parsed = _split(f.name) if f.is_file() else None
        if parsed:
            base, when, n = parsed
            groups.setdefault((f.parent, base), []).append((when, n, f))

    doomed = []
    for gens in groups.values():
        gens.sort(reverse=True)  # 新しい順
        for i, (when, _, f) in enumerate(gens):
            if i < min_keep:
                continue
            too_many = max_gen is not None and i >= max_gen
            too_old = max_age is not None and now - when > timedelta(days=max_age)
            if too_many or too_old:
                doomed.append(f)
    return sorted(doomed)


def run(vault: Vault, retention: dict, now: datetime, dry_run: bool = False) -> list[Path]:
    doomed = plan(vault, retention, now)
    if dry_run:
        return doomed
    for f in doomed:
        f.unlink()
        vault.log(now, op="prune", generation=f.relative_to(vault.root).as_posix())
    return doomed
