"""設定ファイル (sessionvault.json) の読み書き。形は docs/design.md §2.1"""
import copy
import json
from pathlib import Path

DEFAULTS: dict = {
    "vault": None,
    "include_memory": True,
    "retention": {
        "max_generations": None,
        "max_age_days": None,
        "min_keep": 3,
    },
}

# config set で受け付けるキーと、値の読み方
_PARSERS = {
    "vault": lambda s: s or None,
    "include_memory": lambda s: _parse_bool(s),
    "retention.max_generations": lambda s: _parse_optional_int(s),
    "retention.max_age_days": lambda s: _parse_optional_int(s),
    "retention.min_keep": lambda s: int(s),
}


def keys() -> list[str]:
    return list(_PARSERS)


def _parse_bool(s: str) -> bool:
    if s.lower() in ("true", "1", "yes", "on"):
        return True
    if s.lower() in ("false", "0", "no", "off"):
        return False
    raise ValueError(f"true か false を指定してください: {s}")


def _parse_optional_int(s: str) -> int | None:
    if s.lower() in ("", "null", "none"):
        return None
    n = int(s)
    if n < 0:
        raise ValueError(f"0 以上を指定してください: {s}")
    return n


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: Path) -> dict:
    """設定を読む。ファイルが無ければ既定値。知らないキーは残す（新しい版の設定を壊さない）"""
    if not path.is_file():
        return copy.deepcopy(DEFAULTS)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"設定ファイルの中身がオブジェクトではありません: {path}")
    return _merge(DEFAULTS, data)


def save(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def get(cfg: dict, key: str):
    node = cfg
    for part in key.split("."):
        node = node[part]
    return node


def set_value(cfg: dict, key: str, raw: str) -> dict:
    """key に raw を読んだ値を入れた新しい設定を返す。知らないキーは KeyError"""
    if key not in _PARSERS:
        raise KeyError(key)
    value = _PARSERS[key](raw)
    out = copy.deepcopy(cfg)
    *parents, last = key.split(".")
    node = out
    for part in parents:
        node = node.setdefault(part, {})
    node[last] = value
    return out
