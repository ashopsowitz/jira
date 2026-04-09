"""Minimal Jira Cloud REST API v3 client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(email, api_token)
        self.session.headers.update({"Accept": "application/json"})
        self._sprint_field_id: str | None = None

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

        try:
            return response.json()
        except ValueError as exc:
            raise JiraClientError("Jira API returned invalid JSON.") from exc

    def _resolve_sprint_field_id(self) -> str | None:
        if self._sprint_field_id is not None:
            return self._sprint_field_id

        # Some Jira tenants block /field for certain users. Sprint is optional,
        # so we should not fail the whole issue refresh when this lookup fails.
        try:
            fields = self._request("GET", "/rest/api/3/field")
        except JiraClientError:
            self._sprint_field_id = None
            return None

        if not isinstance(fields, list):
            self._sprint_field_id = None
            return None

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

    def _extract_sprint_from_fields(self, fields: dict[str, Any], sprint_field_id: str | None) -> str | None:
        """Best-effort sprint extraction across Jira tenant variations."""
        if sprint_field_id:
            sprint_value = fields.get(sprint_field_id)
            if isinstance(sprint_value, list) and sprint_value:
                last_sprint = sprint_value[-1]
                if isinstance(last_sprint, dict):
                    return last_sprint.get("name")
            elif isinstance(sprint_value, dict):
                return sprint_value.get("name")
            elif isinstance(sprint_value, str):
                return sprint_value

        # Fallback heuristic for cases where sprint field discovery is blocked.
        for value in fields.values():
            if isinstance(value, dict) and "name" in value and "state" in value:
                return value.get("name")
            if isinstance(value, list) and value and isinstance(value[-1], dict):
                item = value[-1]
                if "name" in item and "state" in item:
                    return item.get("name")
        return None

    def _fetch_issue_via_search_fallback(
        self, issue_key: str, requested_fields: list[str]
    ) -> dict[str, Any] | None:
        """Fallback when issue payload comes back without usable fields."""
        payload = self._request(
            "GET",
            "/rest/api/3/search",
            params={
                "jql": f"key = {issue_key}",
                "maxResults": 1,
                "fields": ",".join(requested_fields),
            },
        )
        if not isinstance(payload, dict):
            return None
        issues = payload.get("issues")
        if not isinstance(issues, list) or not issues:
            return None
        first = issues[0]
        return first if isinstance(first, dict) else None

    def fetch_issue(self, issue_key: str) -> JiraIssueData:
        sprint_field_id = self._resolve_sprint_field_id()

        requested_fields = ["summary", "status"]
        if sprint_field_id:
            requested_fields.append(sprint_field_id)

        issue = self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": ",".join(requested_fields)},
        )

        if not isinstance(issue, dict):
            raise JiraClientError("Unexpected Jira issue payload format.")

        fields = issue.get("fields")
        if not isinstance(fields, dict):
            # Some environments/proxies return sparse issue payloads.
            fallback_issue = self._fetch_issue_via_search_fallback(issue_key, requested_fields)
            if isinstance(fallback_issue, dict):
                issue = fallback_issue
                fields = issue.get("fields")
        if not isinstance(fields, dict):
            raise JiraClientError("Issue payload missing fields data.")

        try:
            comments = self._fetch_comments(issue_key)
            latest_comment = extract_latest_comment(comments)
        except JiraClientError as exc:
            # Keep primary issue fields available even if comment API fails
            # (common with permission restrictions).
            latest_comment = {
                "latest_comment_text": f"[Comments unavailable: {exc}]",
                "latest_comment_author": None,
                "latest_comment_timestamp": None,
            }

        summary = fields.get("summary")
        status_obj = fields.get("status") or {}
        status = status_obj.get("name") if isinstance(status_obj, dict) else None
        sprint = self._extract_sprint_from_fields(fields, sprint_field_id)

        return JiraIssueData(
            issue_key=issue_key,
            summary=summary,
            status=status,
            sprint=sprint,
            latest_comment_text=latest_comment["latest_comment_text"],
            latest_comment_author=latest_comment["latest_comment_author"],
            latest_comment_timestamp=latest_comment["latest_comment_timestamp"],
        )
