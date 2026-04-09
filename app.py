from __future__ import annotations

import os
from typing import Iterable

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from jira_client import JiraClient, JiraClientError
from storage import WatchlistStore
from url_parser import extract_issue_key


load_dotenv()

st.set_page_config(page_title="Local Jira Watchlist", layout="wide")
st.title("📌 Local Jira Watchlist")
st.caption("Paste Jira issue URLs, sync details, and keep a local SQLite watchlist.")

store = WatchlistStore(db_path="watchlist.db")

base_url = os.getenv("JIRA_BASE_URL", "").strip()
email = os.getenv("JIRA_EMAIL", "").strip()
api_token = os.getenv("JIRA_API_TOKEN", "").strip()

has_credentials = all([base_url, email, api_token])
client = JiraClient(base_url, email, api_token) if has_credentials else None

if not has_credentials:
    st.warning("Missing Jira credentials. Fill JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN in .env.")


def _refresh(issue_key_list: Iterable[str]) -> None:
    if not has_credentials or client is None:
        st.error("Cannot refresh without Jira credentials in environment variables.")
        return

    keys = list(issue_key_list)
    if not keys:
        st.info("No tickets selected for refresh.")
        return

    progress = st.progress(0, text="Refreshing tickets...")
    total = len(keys)

    for idx, issue_key in enumerate(keys, start=1):
        try:
            issue = client.fetch_issue(issue_key)
            store.save_sync_result(issue_key, issue, None)
        except JiraClientError as exc:
            store.save_sync_result(issue_key, None, str(exc))
        progress.progress(int(idx * 100 / total), text=f"Refreshed {idx}/{total}: {issue_key}")

    st.success(f"Refresh complete for {total} ticket(s).")

with st.expander("Add Jira URLs"):
    pasted = st.text_area(
        "One Jira URL per line (or issue key)",
        placeholder="https://yourorg.atlassian.net/browse/ABC-123",
        height=120,
    )
    add_clicked = st.button("Add tickets to watchlist", type="primary")

if add_clicked:
    lines = [line.strip() for line in pasted.splitlines() if line.strip()]
    if not lines:
        st.info("Nothing to add.")
    else:
        added, duplicate, invalid = 0, 0, []
        added_keys: list[str] = []
        for line in lines:
            issue_key = extract_issue_key(line)
            if not issue_key:
                invalid.append(line)
                continue
            inserted = store.add_issue(issue_key, line)
            if inserted:
                added += 1
                added_keys.append(issue_key)
            else:
                duplicate += 1

        if added:
            st.success(f"Added {added} ticket(s).")
            if has_credentials:
                st.info("Refreshing newly added tickets...")
                _refresh(added_keys)
        if duplicate:
            st.info(f"Skipped {duplicate} duplicate ticket(s).")
        if invalid:
            st.error("Invalid URL(s) or keys:\n- " + "\n- ".join(invalid))

st.sidebar.header("Options")
auto_refresh_mins = st.sidebar.selectbox("Auto-refresh interval (minutes)", [0, 2, 5, 10], index=0)
if auto_refresh_mins > 0:
    st.markdown(
        f"<meta http-equiv='refresh' content='{auto_refresh_mins * 60}'>",
        unsafe_allow_html=True,
    )

if st.sidebar.button("Seed sample data"):
    store.seed_demo_data()
    st.sidebar.success("Seeded demo issues DEMO-1 and DEMO-2.")

rows = store.list_issues()
df = pd.DataFrame(rows)

if df.empty:
    st.info("Watchlist is empty. Add a few Jira URLs above.")
    st.stop()

column_config = {
    "issue_url": st.column_config.LinkColumn("URL"),
    "latest_comment_text": st.column_config.TextColumn("Latest comment", width="large"),
    "error_message": st.column_config.TextColumn("Last error", width="medium"),
}

st.subheader("Current Watchlist")
st.dataframe(df, use_container_width=True, column_config=column_config)

issue_keys = df["issue_key"].tolist()
selected_keys = st.multiselect("Select tickets", options=issue_keys, default=[])

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Refresh selected"):
        _refresh(selected_keys)
        st.rerun()
with col2:
    if st.button("Refresh all"):
        _refresh(issue_keys)
        st.rerun()
with col3:
    if st.button("Remove selected"):
        removed = store.remove_issues(selected_keys)
        st.success(f"Removed {removed} ticket(s).")
        st.rerun()
