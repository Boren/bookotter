# Hardcover GraphQL Pagination Probe Results

**Date**: 2026-04-29  
**Probe Script**: `scripts/probe_hardcover_pagination.py`  
**Evidence**: `.sisyphus/evidence/task-1-probe-output.txt`

## Pagination Scheme

**OFFSET-based pagination** — The Hardcover API supports both `limit` and `offset` parameters for paginating through user books.

## Max Books Per Query

**86 books** — The user's "Want to Read" list contains 86 books. The API returns all 86 books when queried without limit/offset parameters.

## Pagination Support

| Parameter | Supported | Notes |
|-----------|-----------|-------|
| `limit` | ✓ Yes | Limits the number of books returned per query |
| `offset` | ✓ Yes | Skips the first N books, enabling pagination |
| `cursor` | ✗ No | Not tested; offset-based pagination is available |

## Test Results

### Test 1: No Limit/Offset
- **Query**: `user_books(where: {status_id: {_in: $statusIds}})`
- **Result**: Returned 86 books
- **Conclusion**: API returns all books by default

### Test 2: With Limit
- **Query**: `user_books(where: {status_id: {_in: $statusIds}}, limit: 5)`
- **Result**: Returned 5 books
- **Conclusion**: `limit` parameter is supported and respected

### Test 3: With Offset
- **Query**: `user_books(where: {status_id: {_in: $statusIds}}, offset: 5)`
- **Result**: Returned 81 books (86 - 5 offset)
- **Conclusion**: `offset` parameter is supported and respected

## Example Response Shape

```json
{
  "data": {
    "me": [
      {
        "user_books": [
          {
            "status_id": 1,
            "book": {
              "id": 955288,
              "title": "How to Make an Apple Pie from Scratch: In Search of the Recipe for Our Universe"
            }
          }
        ]
      }
    ]
  }
}
```

## Task 11 Implementation Strategy

**Implement server-side pagination with limit + offset.**

The Hardcover API fully supports offset-based pagination. Task 11 should:

1. Accept `limit` and `offset` query parameters from the frontend
2. Pass these to the Hardcover API in the `user_books()` query
3. Return paginated results with metadata (total count, current page, etc.)
4. No client-side chunking needed — pagination is handled server-side

### Recommended Pagination Parameters

- **Default limit**: 20-50 books per page (balance between API calls and response size)
- **Max limit**: 100 books per page (respect API rate limits)
- **Offset**: 0-based index for pagination

### Example Query with Pagination

```graphql
query GetBooksByStatus($statusIds: [Int!]!, $limit: Int!, $offset: Int!) {
  me {
    user_books(where: {status_id: {_in: $statusIds}}, limit: $limit, offset: $offset) {
      status_id
      book {
        id
        title
        # ... other fields
      }
    }
  }
}
```

## Notes

- The API respects both `limit` and `offset` parameters
- No cursor-based pagination is needed
- Rate limiting is 60 requests per minute (1 second delay between requests)
- The probe tested with status ID 1 (Want to Read); other statuses should behave identically
