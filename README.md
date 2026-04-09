# Local Jira Watchlist (Streamlit + SQLite)

A small local-only app to track Jira issues you care about.

## Features

- Paste one or more Jira issue URLs (one per line).
- Robust Jira key extraction from common URL patterns.
- Local watchlist persistence in SQLite (`watchlist.db`).
- Refresh selected/all tickets from Jira Cloud REST API v3.
- Displays:
  - issue key
  - summary
  - status
  - sprint (if configured in your Jira instance)
  - latest comment text
  - latest comment author
  - latest comment timestamp
  - last refreshed timestamp
  - last error (if refresh fails)
- Handles partial failures: one failing ticket doesn't block others.
- Optional auto-refresh via browser refresh meta tag.
- Includes a small demo seed option for local UI testing.

## Tech Stack

- Python 3.11
- Streamlit
- SQLite (`sqlite3` in stdlib)
- requests
- python-dotenv

## Setup

1. **Create and activate a Python 3.11 virtual environment**

   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**

   ```bash
   cp .env.example .env
   ```

   Then edit `.env`:

   - `JIRA_BASE_URL` (example: `https://yourorg.atlassian.net`)
   - `JIRA_EMAIL` (Atlassian account email)
   - `JIRA_API_TOKEN` (API token)

4. **Run the app**

   ```bash
   streamlit run app.py
   ```

This is the one-command run target after setup.

## Notes on Jira fields

- `status` uses `fields.status.name`.
- `sprint` is resolved by discovering the custom field named `Sprint` via `/rest/api/3/field`.
- Latest comment is chosen by newest `created` timestamp and converted to plain text (ADF supported for common node types).

## Error handling

Refresh errors are captured per issue and stored in SQLite. Common cases:

- 401 Unauthorized (bad email/token)
- 403 Forbidden (missing access)
- 404 Not found
- 429 Rate limited
- Network/timeout errors

## Local persistence

The app creates `watchlist.db` in the project folder. Data survives app restarts.

## Project structure

- `app.py` – Streamlit UI
- `jira_client.py` – Jira API helper
- `url_parser.py` – issue key extraction logic
- `comment_utils.py` – latest comment extraction + ADF text conversion
- `storage.py` – SQLite CRUD
- `.env.example` – env var template
- `requirements.txt` – dependencies
