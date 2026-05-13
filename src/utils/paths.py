"""Repository-root path helpers."""

from __future__ import annotations

from pathlib import Path
from typing import overload

REPO_ROOT = Path(__file__).resolve().parents[2]


@overload
def resolve_repo_path(path: None) -> None: ...


@overload
def resolve_repo_path(path: str | Path) -> Path: ...


def resolve_repo_path(path: str | Path | None) -> Path | None:
    """Resolve relative paths from the repository root, not the process cwd."""

    if path is None:
        return None
    value = Path(path).expanduser()
    if value.is_absolute():
        return value
    return REPO_ROOT / value
