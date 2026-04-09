"""Utilities for parsing Jira issue keys from pasted URLs or plain text."""

from __future__ import annotations

import re
from urllib.parse import urlparse

ISSUE_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_issue_key(raw_value: str) -> str | None:
    """Extract a Jira issue key from a URL or free-form text.

    Supports common Jira Cloud URL formats like:
      - https://company.atlassian.net/browse/ABC-123
      - https://company.atlassian.net/jira/software/c/projects/ABC/issues/ABC-123
      - ...selectedIssue=ABC-123

    Returns an uppercase issue key or None.
    """
    candidate = (raw_value or "").strip()
    if not candidate:
        return None

    # Fast path: user pasted only the issue key.
    direct_match = ISSUE_KEY_PATTERN.search(candidate.upper())
    if direct_match and candidate.upper() == direct_match.group(1):
        return direct_match.group(1)

    parsed = urlparse(candidate)
    search_space = " ".join(
        filter(
            None,
            [
                parsed.path,
                parsed.query,
                parsed.fragment,
                candidate,
            ],
        )
    ).upper()

    match = ISSUE_KEY_PATTERN.search(search_space)
    if not match:
        return None
    return match.group(1)
