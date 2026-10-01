"""verify: 元のセッションと保管庫を検査する。検査項目は docs/design.md §4。何も書き換えない"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .backup import iter_targets
from .vault import Vault, long_path, project_child

ERROR, WARNING, INFO = "error", "warning", "info"


@dataclass
class Finding:
    session: str | None
    project: str
    path: str         # プロジェクトからの相対パス（/ 区切り）
    check: str
    severity: str
    line: int | None  # 1 始まり
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def session_of(rel: str) -> str | None:
    """<sid>.jsonl と <sid>/... からセッション ID を取る。memory など、セッションに属さないものは None"""
    head = rel.split("/", 1)[0]
    if head == "memory":
        return None
    return head[: -len(".jsonl")] if head.endswith(".jsonl") else head


@dataclass
class _Parsed:
    uuids: list            # [(uuid, 行番号)]
    parents: list          # [(parentUuid, 行番号)]


def _scan_jsonl(data: bytes, project: str, rel: str, out: list) -> _Parsed:
    sid = session_of(rel)
    parsed = _Parsed([], [])
    lines = data.split(b"\n")
    ends_with_newline = lines[-1] == b""
    if ends_with_newline:
        lines.pop()
    last = len(lines)
    truncated = False
    for no, raw in enumerate(lines, 1):
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            if no == last and not ends_with_newline:
                truncated = True
                out.append(Finding(sid, project, rel, "truncated-tail", WARNING, no, f"最後の行が途中で切れています: {e}"))
            else:
                out.append(Finding(sid, project, rel, "bad-json", ERROR, no, str(e)))
            continue
        if not isinstance(rec, dict):
            continue  # 知らない形の行はそのまま扱う
        if isinstance(rec.get("uuid"), str):
            parsed.uuids.append((rec["uuid"], no))
        if isinstance(rec.get("parentUuid"), str):
            parsed.parents.append((rec["parentUuid"], no))
    if lines and not ends_with_newline and not truncated:
        out.append(Finding(sid, project, rel, "no-newline", WARNING, last, "ファイルが改行で終わっていません"))
    return parsed


def _check_session(project: str, files: dict, out: list) -> None:
    """files: {rel: _Parsed}。uuid の重複は 1 ファイルの中、親の検索はセッション全体（本体とサブエージェント）"""
    known = {u for p in files.values() for u, _ in p.uuids}
    for rel, p in files.items():
        sid = session_of(rel)
        seen: dict = {}
        for u, no in p.uuids:
            if u in seen:
                out.append(Finding(sid, project, rel, "duplicate-uuid", WARNING, no, f"{u}（最初は {seen[u]} 行目）"))
            else:
                seen[u] = no
        for parent, no in p.parents:
            if parent not in known:
                out.append(Finding(sid, project, rel, "dangling-parent", ERROR, no, f"parentUuid {parent} がどこにもありません"))


def _check_mirror(data: bytes, mirror_file: Path, project: str, rel: str, out: list) -> None:
    if not mirror_file.is_file():
        return
    old = mirror_file.read_bytes()
    cur = data[: data.rfind(b"\n") + 1]  # backup と同じく、書きかけの最後の行は数えない
    if len(cur) < len(old):
        out.append(Finding(session_of(rel), project, rel, "diverged", ERROR, None,
                           f"元（{len(cur)} バイト）が保管庫（{len(old)} バイト）より短くなっています"))
    elif not cur.startswith(old):
        out.append(Finding(session_of(rel), project, rel, "diverged", ERROR, None, "元の先頭が保管庫の版と一致しません"))


def run(src: Path, vault_root: Path | None = None, session: str | None = None,
        include_memory: bool = True, projects: list[str] | None = None) -> list[Finding]:
    """projects はプロジェクト名の一覧（大文字・小文字は無視）。そのプロジェクトだけを検査する"""
    src = long_path(src)
    want_project = {p.casefold() for p in projects} if projects else None
    vault = Vault(vault_root) if vault_root else None
    use_mirror = vault is not None and vault.mirror.is_dir()
    want = session.casefold() if session else None
    out: list[Finding] = []
    groups: dict[tuple[str, str | None], dict] = {}
    seen: set[tuple[str, str]] = set()
    mproject_of: dict[str, str] = {}

    for t in iter_targets(src, include_memory):
        if want_project and t.project.casefold() not in want_project:
            continue
        sid = session_of(t.rel)
        seen.add((t.project.casefold(), t.rel.casefold()))
        if want and (sid or "").casefold() != want:
            continue
        if not t.append:
            continue
        try:
            data = t.path.read_bytes()
        except OSError as e:
            out.append(Finding(sid, t.project, t.rel, "unreadable", ERROR, None, str(e)))
            continue
        groups.setdefault((t.project, sid), {})[t.rel] = _scan_jsonl(data, t.project, t.rel, out)
        if use_mirror:
            if t.project not in mproject_of:
                mproject_of[t.project] = project_child(vault.mirror, t.project).name
            _check_mirror(data, vault.mirror / mproject_of[t.project] / t.rel, t.project, t.rel, out)

    for (project, _), files in groups.items():
        _check_session(project, files, out)

    if use_mirror:
        for project in sorted(vault.mirror.iterdir()):
            if not project.is_dir() or (want_project and project.name.casefold() not in want_project):
                continue
            for f in sorted(project.rglob("*")):
                if not f.is_file() or f.name.endswith(".sv-tmp"):
                    continue
                rel = f.relative_to(project).as_posix()
                if (project.name.casefold(), rel.casefold()) in seen:
                    continue
                if not include_memory and rel.startswith("memory/"):
                    continue
                if want and (session_of(rel) or "").casefold() != want:
                    continue
                out.append(Finding(session_of(rel), project.name, rel, "src-missing", INFO, None,
                                   "保管庫にはあるが、元にはありません"))

    order = {ERROR: 0, WARNING: 1, INFO: 2}
    out.sort(key=lambda f: (order[f.severity], f.project, f.path, f.line or 0))
    return out
