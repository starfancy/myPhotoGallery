from __future__ import annotations

import os
from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a supplied relative path escapes its root."""


def normalize_relative(raw: str) -> str:
    """Normalize a user-supplied relative path.

    - Converts backslashes to forward slashes.
    - Strips leading slashes.
    - Collapses `.` segments and double slashes.
    - Rejects `..` segments, absolute Windows drive letters, null bytes.
    Returns "" for empty / root-relative input.
    """
    if raw is None:
        return ""
    if "\x00" in raw:
        raise PathTraversalError("null byte in path")
    s = raw.replace("\\", "/").strip()
    # reject absolute drive letter like "C:/..."
    if len(s) >= 2 and s[1] == ":":
        raise PathTraversalError("absolute drive path not allowed")
    parts: list[str] = []
    for seg in s.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise PathTraversalError("parent segment '..' not allowed")
        parts.append(seg)
    return "/".join(parts)


def resolve_within_root(root_abs: str | Path, rel: str) -> Path:
    """Return realpath of `root_abs/rel`, ensuring it stays under root.

    Raises PathTraversalError if the resolved target escapes the root
    (via `..`, symlink, or any other means).
    """
    root_resolved = Path(root_abs).resolve()
    clean = normalize_relative(rel)
    target = (root_resolved / clean).resolve() if clean else root_resolved
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise PathTraversalError(
            f"resolved path {target} escapes root {root_resolved}"
        ) from exc
    return target
