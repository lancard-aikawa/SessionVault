"""保管庫の形（docs/design.md §2）と、そこへの書き込みの部品"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 1
TS_FORMAT = "%Y%m%dT%H%M%SZ"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(TS_FORMAT)


def parse_ts(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def long_path(p: Path) -> Path:
    """Windows で 260 文字を超えるパスも扱えるよう \\\\?\\ を付ける。世代は名前に @時刻 が付くので長くなりやすい"""
    if sys.platform != "win32":
        return Path(p)
    s = os.path.abspath(p)
    if s.startswith("\\\\?\\"):
        return Path(s)
    if s.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + s[2:])
    return Path("\\\\?\\" + s)


class Vault:
    def __init__(self, root: Path):
        self.root = long_path(root)
        self.mirror = self.root / "mirror"
        self.generations = self.root / "generations"
        self.log_dir = self.root / "log"
        self.index_dir = self.root / "index"

    def ensure(self, src: Path) -> None:
        """vault.json が無ければ作る。形式の版が新しすぎれば止める"""
        meta = self.root / "vault.json"
        if meta.is_file():
            with open(meta, encoding="utf-8") as f:
                fmt = json.load(f).get("format")
            if not isinstance(fmt, int) or fmt > FORMAT:
                raise ValueError(f"この版では読めない保管庫です（format={fmt!r}）: {self.root}")
            return
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(meta, {"format": FORMAT, "src": str(src), "created": utc_now().isoformat(timespec="seconds")})

    def log(self, when: datetime, **entry) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{when.astimezone(timezone.utc):%Y-%m}.jsonl"
        line = json.dumps({"time": when.isoformat(timespec="seconds"), **entry}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")

    def new_generation_path(self, project: str, rel: str, when: datetime) -> Path:
        """まだ使われていない世代の場所。同じ秒に 2 回押し出したら -1, -2 … を付ける"""
        base = self.generations / project / f"{rel}@{ts(when)}"
        dest, n = base, 0
        while dest.exists():
            n += 1
            dest = base.with_name(f"{base.name}-{n}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def push_generation(self, project: str, rel: str, when: datetime) -> Path:
        """mirror のファイルを generations へ移す"""
        dest = self.new_generation_path(project, rel, when)
        os.replace(self.mirror / project / rel, dest)
        return dest

    def stash(self, project: str, rel: str, data: bytes, when: datetime) -> Path:
        """元の場所を上書きする前に、その中身を世代として残す"""
        dest = self.new_generation_path(project, rel, when)
        write_bytes_atomic(dest, data)
        return dest

    def generations_of(self, project: str, rel: str) -> list[tuple[str, Path]]:
        """rel の世代を古い順に [(名前の @ より後ろ, パス)]"""
        d = (self.generations / project / rel).parent
        name = rel.rsplit("/", 1)[-1] + "@"
        if not d.is_dir():
            return []
        return sorted((f.name[len(name):], f) for f in d.iterdir() if f.is_file() and f.name.startswith(name))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path: Path, default):
    if not path.is_file():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """一時ファイルに書いてから置き換える。書きかけを残さない"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.sv-tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def find_session(root: Path, session: str) -> list[Path]:
    """root（projects と同じ木の形）から <session>.jsonl を探す。大文字・小文字は無視する"""
    key = f"{session}.jsonl".casefold()
    if not root.is_dir():
        return []
    return sorted(f for p in root.iterdir() if p.is_dir()
                  for f in p.iterdir() if f.is_file() and f.name.casefold() == key)


def project_child(root: Path, name: str) -> Path:
    """root の下の name を、大文字・小文字を無視して探す。無ければ name のまま"""
    if root.is_dir():
        key = name.casefold()
        for child in root.iterdir():
            if child.name.casefold() == key:
                return child
    return root / name
