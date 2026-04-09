"""Helpers for Jira comment extraction and ADF-to-text conversion."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_jira_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Jira Cloud timestamps generally look like: 2024-01-20T14:31:09.522+0000
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def _adf_node_to_text(node: Any) -> str:
    """Convert a subset of Atlassian Document Format to plain text."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type")
    if node_type == "text":
        return node.get("text", "")
    if node_type in {"hardBreak", "rule"}:
        return "\n"

    content = node.get("content", [])
    joined = "".join(_adf_node_to_text(child) for child in content)

    if node_type in {"paragraph", "heading"}:
        return f"{joined}\n"
    if node_type in {"bulletList", "orderedList"}:
        return f"{joined}\n"
    if node_type == "listItem":
        return f"- {joined}" if joined else ""

    return joined


def adf_to_plain_text(value: Any) -> str:
    """Convert Jira comment body to plain text.

    Jira may return either plain string or ADF dict.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        text = _adf_node_to_text(value)
        # normalize excessive blank lines
        lines = [line.rstrip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line or (lines and line == "")).strip()
    return str(value)


def extract_latest_comment(comments: list[dict[str, Any]]) -> dict[str, str | None]:
    """Return latest comment info by created timestamp."""
    if not comments:
        return {
            "latest_comment_text": None,
            "latest_comment_author": None,
            "latest_comment_timestamp": None,
        }

    latest = max(
        comments,
        key=lambda c: _parse_jira_datetime(c.get("created")) or datetime.min,
    )
    author = (latest.get("author") or {}).get("displayName")
    created = latest.get("created")
    body = adf_to_plain_text(latest.get("body"))

    return {
        "latest_comment_text": body or None,
        "latest_comment_author": author,
        "latest_comment_timestamp": created,
    }
