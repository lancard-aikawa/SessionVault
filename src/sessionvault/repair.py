"""repair: 壊れたセッションを直した版を作る。規則は docs/design.md §5"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_UUID = re.compile(rb'"uuid"\s*:\s*"([^"\\]+)"')
_PARENT = re.compile(rb'"parentUuid"\s*:\s*(?:"([^"\\]+)"|null)')


@dataclass
class Repaired:
    data: bytes
    notes: list = field(default_factory=list)   # [(行番号, 何をしたか)]

    @property
    def changed(self) -> bool:
        return bool(self.notes)


def subagent_uuids(session_file: Path) -> frozenset:
    """<sid>.jsonl と同じセッションのサブエージェントにある uuid"""
    out = set()
    sub = session_file.with_suffix("") / "subagents"
    for f in sorted(sub.rglob("*.jsonl")) if sub.is_dir() else []:
        for m in _UUID.finditer(f.read_bytes()):
            out.add(m.group(1).decode("utf-8", "replace"))
    return frozenset(out)


def repair_bytes(data: bytes, known_elsewhere: frozenset = frozenset()) -> Repaired:
    """壊れた行を落とし、落とした行を親にしていた行を、その親につなぎ直す。手を入れない行はバイト列のまま。
    known_elsewhere は同じセッションのサブエージェントにある uuid（そこを指す親は行き先ありとみなす）"""
    lines = data.split(b"\n")
    ends_with_newline = lines[-1] == b""
    if ends_with_newline:
        lines.pop()
    notes = []
    kept: list[tuple[int, bytes, dict | None]] = []
    dropped: dict[str, str | None] = {}   # 落とした行の uuid → その親
    tail_dropped = False
    unnamed: list[tuple[int, str | None]] = []   # uuid は読めず親だけ読めた壊れた行 (行番号, 親)

    for no, raw in enumerate(lines, 1):
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if no == len(lines) and not ends_with_newline:
                tail_dropped = True
                notes.append((no, "途中で切れた最後の行を落としました"))
            else:
                notes.append((no, "JSON として読めない行を落としました"))
            # 壊れた行からも uuid と親が読めれば、子をつなぎ直せる
            m, p = _UUID.search(raw), _PARENT.search(raw)
            parent = p.group(1).decode("utf-8", "replace") if p and p.group(1) else None
            if m:
                dropped[m.group(1).decode("utf-8", "replace")] = parent
            elif p:
                unnamed.append((no, parent))
            continue
        kept.append((no, raw, rec if isinstance(rec, dict) else None))

    # Claude Code の行は parentUuid が先頭、uuid が後ろの方にある。後半が欠けた行は uuid が読めないので、
    # その行より後で初めて出てくる「行き先の無い parentUuid」を、その行の uuid だったとみなす
    known = {r["uuid"] for _, _, r in kept if r and isinstance(r.get("uuid"), str)} | set(known_elsewhere)
    for at, parent in unnamed:
        for no, _, rec in kept:
            orphan = rec.get("parentUuid") if rec else None
            if no > at and isinstance(orphan, str) and orphan not in known and orphan not in dropped:
                dropped[orphan] = parent
                break

    out = []
    for no, raw, rec in kept:
        parent = rec.get("parentUuid") if rec else None
        if isinstance(parent, str) and parent in dropped:
            new_parent, hops = parent, 0
            while new_parent in dropped and hops <= len(dropped):  # 落とした行が続いていれば辿る
                new_parent, hops = dropped[new_parent], hops + 1
            rec = dict(rec, parentUuid=new_parent)
            raw = json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            notes.append((no, f"parentUuid を {parent} から {new_parent} につなぎ直しました"))
        out.append(raw)

    fixed = b"".join(r + b"\n" for r in out)
    if lines and not ends_with_newline and not tail_dropped:
        notes.append((len(lines), "最後に改行を足しました"))
    notes.sort(key=lambda n: n[0])
    return Repaired(fixed, notes)
