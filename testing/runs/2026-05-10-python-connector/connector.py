"""
Linear GraphQL connector — fetches all issues from the Linear API.

Authentication: pass LINEAR_API_KEY as the `api_key` static param in the YAML,
referencing {{ env.LINEAR_API_KEY }} so the value is resolved at runtime.

Pagination is cursor-based (pageInfo.hasNextPage + endCursor). The connector
handles all pages in a single call and returns a flat list[dict].
"""
from __future__ import annotations

import requests

_GRAPHQL_URL = "https://api.linear.app/graphql"

_QUERY = """
query FetchIssues($cursor: String) {
  issues(first: 100, after: $cursor) {
    nodes {
      id
      title
      state { name }
      priority
      assignee { name }
      createdAt
      updatedAt
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


def fetch_issues(dynamic_params: dict) -> list[dict]:
    """
    Fetch all Linear issues across all cursor pages.
    Returns a flat list of dicts with nested fields pre-flattened.
    """
    api_key = dynamic_params["api_key"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    records: list[dict] = []
    cursor: str | None = None

    while True:
        resp = requests.post(
            _GRAPHQL_URL,
            json={"query": _QUERY, "variables": {"cursor": cursor}},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()

        if "errors" in body:
            raise RuntimeError(f"GraphQL errors: {body['errors']}")

        connection = body["data"]["issues"]
        for node in connection["nodes"]:
            records.append({
                "id": node["id"],
                "title": node["title"],
                "state_name": node["state"]["name"] if node.get("state") else None,
                "priority": node.get("priority"),
                "assignee_name": node["assignee"]["name"] if node.get("assignee") else None,
                "created_at": node.get("createdAt"),
                "updated_at": node.get("updatedAt"),
            })

        page_info = connection["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return records
