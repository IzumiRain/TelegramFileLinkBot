"""Minimal .env reader/writer that preserves comments and key order.

Used by the web admin panel (saving settings) and by install.sh
(writing the answers it collected). python-dotenv reads .env fine for
the app itself; this module exists for *editing* it without mangling
the file a human may also edit by hand.
"""
from __future__ import annotations

import re
from pathlib import Path

_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    # unquoted: a trailing comment is not part of the value
    return value.split(" #", 1)[0].strip()


def _quote(value: str) -> str:
    if value == "":
        return ""
    if re.search(r"[\s#'\"$`\\]", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def parse_env_file(path: Path) -> dict[str, str]:
    """All KEY=VALUE pairs in the file (comments/blank lines ignored)."""
    result: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        match = _LINE_RE.match(line)
        if match:
            result[match.group(1)] = _unquote(match.group(2))
    return result


def update_env_file(path: Path, updates: dict[str, str | None]) -> None:
    """Apply updates in place.

    Existing keys are rewritten on their own line (comments elsewhere in
    the file are untouched), new keys are appended, and a value of None
    removes the key. The file is created when missing.
    """
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        match = _LINE_RE.match(line)
        if match and match.group(1) in remaining:
            key = match.group(1)
            value = remaining.pop(key)
            if value is not None:
                out.append(f"{key}={_quote(value)}")
            # None → drop the line entirely
        else:
            out.append(line)
    for key, value in remaining.items():
        if value is not None:
            out.append(f"{key}={_quote(value)}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
