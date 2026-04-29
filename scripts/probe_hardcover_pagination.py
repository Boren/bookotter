#!/usr/bin/env python3
"""
Hardcover GraphQL Pagination Probe

Tests Hardcover API pagination support and documents the results.
This probe determines whether Task 11 should use server-side pagination or client-side chunking.

Exit codes:
  0: Success - pagination tested and documented
  1: Missing hardcover.api_token in config
  2: API request failed
"""

import json
import sys
from pathlib import Path

import requests

# Add backend to path for config loading
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import load_config


def probe_pagination() -> dict:
    """
    Probe Hardcover API for pagination support.

    Returns:
        Dictionary with pagination details:
        - pagination_scheme: 'offset', 'cursor', or 'none'
        - max_books_per_query: Maximum books returned in single query
        - supports_limit: Whether API accepts limit parameter
        - supports_offset: Whether API accepts offset parameter
        - example_response: Sample response structure
        - notes: Additional observations
    """
    config = load_config()
    api_token = config.get("hardcover", {}).get("api_token", "").strip()
    api_url = config.get("hardcover", {}).get("api_url", "https://api.hardcover.app/v1/graphql")

    if not api_token:
        print("ERROR: missing hardcover.api_token in config", file=sys.stderr)
        sys.exit(1)

    headers = {
        "Content-Type": "application/json",
        "Authorization": api_token,
        "User-Agent": "BookOtter/probe",
    }

    results = {
        "pagination_scheme": None,
        "max_books_per_query": None,
        "supports_limit": False,
        "supports_offset": False,
        "example_response": None,
        "notes": [],
    }

    # Test 1: Query with no limit/offset to find max books returned
    print("Test 1: Querying without limit/offset to find max books returned...")
    query_no_limit = """
    query GetBooksByStatus($statusIds: [Int!]!) {
      me {
        user_books(where: {status_id: {_in: $statusIds}}) {
          status_id
          book {
            id
            title
          }
        }
      }
    }
    """

    try:
        response = requests.post(
            api_url,
            json={"query": query_no_limit, "variables": {"statusIds": [1]}},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            print(f"GraphQL error: {data['errors']}", file=sys.stderr)
            sys.exit(2)

        me_data = data.get("data", {}).get("me", [])
        if isinstance(me_data, list) and len(me_data) > 0:
            user_books = me_data[0].get("user_books", [])
        elif isinstance(me_data, dict):
            user_books = me_data.get("user_books", [])
        else:
            user_books = []

        max_books = len(user_books)
        results["max_books_per_query"] = max_books
        results["example_response"] = data
        print(f"  ✓ Returned {max_books} books without limit/offset")

    except Exception as e:
        print(f"ERROR: Test 1 failed: {e}", file=sys.stderr)
        sys.exit(2)

    # Test 2: Try with limit parameter
    print("Test 2: Testing limit parameter (limit: 5)...")
    query_with_limit = """
    query GetBooksByStatus($statusIds: [Int!]!) {
      me {
        user_books(where: {status_id: {_in: $statusIds}}, limit: 5) {
          status_id
          book {
            id
            title
          }
        }
      }
    }
    """

    try:
        response = requests.post(
            api_url,
            json={"query": query_with_limit, "variables": {"statusIds": [1]}},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            error_msg = str(data.get("errors", []))
            if "limit" in error_msg.lower() or "unknown" in error_msg.lower():
                print(f"  ✗ limit parameter not supported: {error_msg}")
                results["notes"].append("limit parameter rejected by API")
            else:
                print(f"  ✗ GraphQL error: {error_msg}")
                results["notes"].append(f"limit parameter error: {error_msg}")
        else:
            me_data = data.get("data", {}).get("me", [])
            if isinstance(me_data, list) and len(me_data) > 0:
                user_books = me_data[0].get("user_books", [])
            elif isinstance(me_data, dict):
                user_books = me_data.get("user_books", [])
            else:
                user_books = []

            limit_books = len(user_books)
            print(f"  ✓ limit parameter accepted, returned {limit_books} books")
            results["supports_limit"] = True

    except Exception as e:
        print(f"  ✗ limit parameter test failed: {e}")
        results["notes"].append(f"limit parameter error: {e}")

    # Test 3: Try with offset parameter
    print("Test 3: Testing offset parameter (offset: 5)...")
    query_with_offset = """
    query GetBooksByStatus($statusIds: [Int!]!) {
      me {
        user_books(where: {status_id: {_in: $statusIds}}, offset: 5) {
          status_id
          book {
            id
            title
          }
        }
      }
    }
    """

    try:
        response = requests.post(
            api_url,
            json={"query": query_with_offset, "variables": {"statusIds": [1]}},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            error_msg = str(data.get("errors", []))
            if "offset" in error_msg.lower() or "unknown" in error_msg.lower():
                print(f"  ✗ offset parameter not supported: {error_msg}")
                results["notes"].append("offset parameter rejected by API")
            else:
                print(f"  ✗ GraphQL error: {error_msg}")
                results["notes"].append(f"offset parameter error: {error_msg}")
        else:
            me_data = data.get("data", {}).get("me", [])
            if isinstance(me_data, list) and len(me_data) > 0:
                user_books = me_data[0].get("user_books", [])
            elif isinstance(me_data, dict):
                user_books = me_data.get("user_books", [])
            else:
                user_books = []

            offset_books = len(user_books)
            print(f"  ✓ offset parameter accepted, returned {offset_books} books")
            results["supports_offset"] = True

    except Exception as e:
        print(f"  ✗ offset parameter test failed: {e}")
        results["notes"].append(f"offset parameter error: {e}")

    # Determine pagination scheme
    if results["supports_limit"] and results["supports_offset"]:
        results["pagination_scheme"] = "offset"
        print("\n✓ Pagination scheme: OFFSET-based (limit + offset)")
    elif results["supports_limit"]:
        results["pagination_scheme"] = "limit_only"
        print("\n✓ Pagination scheme: LIMIT-only (no offset)")
    else:
        results["pagination_scheme"] = "none"
        print("\n✓ Pagination scheme: NONE (fetch all, client-side chunking required)")

    return results


def main():
    """Run the probe and save results."""
    print("=" * 70)
    print("Hardcover GraphQL Pagination Probe")
    print("=" * 70)
    print()

    results = probe_pagination()

    # Save evidence
    evidence_dir = Path(".sisyphus/evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_file = evidence_dir / "task-1-probe-output.txt"

    with open(evidence_file, "w") as f:
        f.write("=" * 70 + "\n")
        f.write("Hardcover GraphQL Pagination Probe Results\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"Pagination Scheme: {results['pagination_scheme']}\n")
        f.write(f"Max Books Per Query: {results['max_books_per_query']}\n")
        f.write(f"Supports limit: {results['supports_limit']}\n")
        f.write(f"Supports offset: {results['supports_offset']}\n")
        f.write("\nNotes:\n")
        for note in results["notes"]:
            f.write(f"  - {note}\n")
        f.write("\nExample Response (first 500 chars):\n")
        if results["example_response"]:
            response_str = json.dumps(results["example_response"], indent=2)
            f.write(response_str[:500] + ("..." if len(response_str) > 500 else "") + "\n")

    print(f"\n✓ Evidence saved to: {evidence_file}")
    print()

    # Print summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Pagination Scheme: {results['pagination_scheme']}")
    print(f"Max Books Per Query: {results['max_books_per_query']}")
    print()

    if results["pagination_scheme"] == "offset":
        print("Task 11 Strategy: Implement server-side pagination with limit + offset")
    elif results["pagination_scheme"] == "limit_only":
        print("Task 11 Strategy: Implement server-side pagination with limit only")
    else:
        print("Task 11 Strategy: Fetch all books client-side, chunk as needed")

    print()
    sys.exit(0)


if __name__ == "__main__":
    main()
