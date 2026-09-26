"""Research report payloads and markdown rendering (pure)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, default=_default, allow_nan=True) + "\n"


def report_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, float | int | str | bool) or value is None:
        return value
    return str(value)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 100 else f"{value:.1f}"
    if isinstance(value, list | tuple):
        return ", ".join(_fmt(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}={_fmt(item)}" for key, item in value.items())
    return str(value)


def render_markdown(title: str, sections: list[tuple[str, Any]]) -> str:
    lines = [f"# {title}", ""]
    for heading, body in sections:
        lines.append(f"## {heading}")
        lines.append("")
        if isinstance(body, Mapping):
            lines.append("| key | value |")
            lines.append("| --- | --- |")
            for key, value in body.items():
                lines.append(f"| {key} | {_fmt(value)} |")
        elif isinstance(body, list):
            for item in body:
                lines.append(f"- {_fmt(item)}")
        else:
            lines.append(str(body))
        lines.append("")
    return "\n".join(lines)
