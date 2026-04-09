"""Minimal Jira Cloud REST API v3 client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth

from comment_utils import extract_latest_comment


@dataclass(slots=True)
class JiraIssueData:
    issue_key: str
    summary: str | None
    status: str | None
    sprint: str | None
    latest_comment_text: str | None
    latest_comment_author: str | None
    latest_comment_timestamp: str | None


class JiraClientError(Exception):
    """Raised for Jira client failures with user-friendly context."""


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str, timeout_seconds: int = 20):
        self.base_url = self._normalize_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(email, api_token)
        self.session.headers.update({"Accept": "application/json"})
        self._sprint_field_id: str | None = None

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        cleaned = base_url.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        return cleaned.rstrip("/")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=self.timeout_seconds, **kwargs)
        except requests.RequestException as exc:
            raise JiraClientError(f"Network error contacting Jira: {exc}") from exc

        if response.status_code == 401:
            raise JiraClientError("Unauthorized (401). Check JIRA_EMAIL / JIRA_API_TOKEN.")
        if response.status_code == 403:
            raise JiraClientError("Forbidden (403). Your account lacks access to this issue.")
        if response.status_code == 404:
            raise JiraClientError("Issue not found (404).")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise JiraClientError(f"Rate limited (429). Retry-After={retry_after}s.")
        if response.status_code >= 400:
            raise JiraClientError(f"Jira API error {response.status_code}: {response.text[:200]}")

        if response.status_code == 204 or not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            content_type = response.headers.get("Content-Type", "unknown")
            body_preview = (response.text or "").strip().replace("\n", " ")[:200]
            if body_preview:
                hint = ""
                if "text/html" in content_type.lower():
                    hint = " Jira base URL should look like https://yourorg.atlassian.net (no /browse path)."
                raise JiraClientError(
                    "Jira API returned a non-JSON response "
                    f"(status={response.status_code}, content-type={content_type}). "
                    f"Check Jira base URL and credentials.{hint} Response starts with: {body_preview!r}"
                ) from exc
            raise JiraClientError(
                "Jira API returned an empty non-JSON response "
                f"(status={response.status_code}, content-type={content_type}). "
                "Check Jira base URL and credentials."
            ) from exc

    def _resolve_sprint_field_id(self) -> str | None:
        if self._sprint_field_id is not None:
            return self._sprint_field_id

        fields = self._request("GET", "/rest/api/3/field")
        sprint_id: str | None = None
        for field in fields:
            if isinstance(field, dict) and (field.get("name") or "").lower() == "sprint":
                sprint_id = field.get("id")
                break
        self._sprint_field_id = sprint_id
        return sprint_id

    def _fetch_comments(self, issue_key: str) -> list[dict[str, Any]]:
        all_comments: list[dict[str, Any]] = []
        start_at = 0
        max_results = 100

        while True:
            payload = self._request(
                "GET",
                f"/rest/api/3/issue/{issue_key}/comment",
                params={"startAt": start_at, "maxResults": max_results},
            )
            values = payload.get("comments", [])
            if isinstance(values, list):
                all_comments.extend(v for v in values if isinstance(v, dict))

            total = int(payload.get("total", len(all_comments)))
            start_at += int(payload.get("maxResults", max_results))
            if len(all_comments) >= total:
                break

        return all_comments

    def fetch_issue(self, issue_key: str) -> JiraIssueData:
        sprint_field_id = self._resolve_sprint_field_id()
        issue = self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": "summary,status"},
        )
        comments = self._fetch_comments(issue_key)
        latest_comment = extract_latest_comment(comments)

        fields = issue.get("fields", {})
        summary = fields.get("summary") if isinstance(fields, dict) else None
        status = None
        sprint = None

        if isinstance(fields, dict):
            status_obj = fields.get("status") or {}
            status = status_obj.get("name") if isinstance(status_obj, dict) else None
            if sprint_field_id:
                sprint_value = fields.get(sprint_field_id)
                if isinstance(sprint_value, list) and sprint_value:
                    last_sprint = sprint_value[-1]
                    if isinstance(last_sprint, dict):
                        sprint = last_sprint.get("name")
                elif isinstance(sprint_value, dict):
                    sprint = sprint_value.get("name")
                elif isinstance(sprint_value, str):
                    sprint = sprint_value

        return JiraIssueData(
            issue_key=issue_key,
            summary=summary,
            status=status,
            sprint=sprint,
            latest_comment_text=latest_comment["latest_comment_text"],
            latest_comment_author=latest_comment["latest_comment_author"],
            latest_comment_timestamp=latest_comment["latest_comment_timestamp"],
        )
