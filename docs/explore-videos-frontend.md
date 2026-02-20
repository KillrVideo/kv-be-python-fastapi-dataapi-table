# Explore Videos — Frontend Integration Guide

## Endpoint

```
GET /api/v1/videos/latest
```

No authentication required (public endpoint).

## Query Parameters

| Parameter  | Type | Default | Range  | Description          |
|------------|------|---------|--------|----------------------|
| `page`     | int  | 1       | >= 1   | Page number          |
| `pageSize` | int  | 10      | 1–100  | Items per page       |

## Example Request

```
GET /api/v1/videos/latest?page=1&pageSize=12
```

## Response Shape

```json
{
  "data": [
    {
      "videoId": "uuid",
      "title": "Video Title",
      "thumbnailUrl": "https://i.ytimg.com/vi/.../hqdefault.jpg",
      "userId": "uuid",
      "submittedAt": "2025-12-01T14:30:00Z",
      "content_rating": null,
      "category": null
    }
  ],
  "pagination": {
    "currentPage": 1,
    "pageSize": 12,
    "totalItems": 47,
    "totalPages": 4
  }
}
```

## Key Fields in Each Video

| Field           | Type        | Notes                                    |
|-----------------|-------------|------------------------------------------|
| `videoId`       | UUID string | Use for routing to `/videos/{videoId}`   |
| `title`         | string      | Display name                             |
| `thumbnailUrl`  | URL or null | YouTube thumbnail; use placeholder if null |
| `userId`        | UUID string | Uploader's user ID                       |
| `submittedAt`   | ISO 8601    | When the video was added                 |
| `content_rating`| string/null | Optional content rating                  |
| `category`      | string/null | Optional category                        |

## Pagination

Use `pagination.totalPages` to render page controls. To fetch the next page:

```
GET /api/v1/videos/latest?page=2&pageSize=12
```

## Suggested UX

- Default to `pageSize=12` (works well in 3- or 4-column grids)
- Show video cards with thumbnail, title, and submission date
- Link each card to the video detail page using `videoId`
- Use `totalItems` to show "Showing X of Y videos"
- Consider infinite scroll or "Load More" using incrementing `page` values

## Sort Order

Videos are sorted **newest first** (by `submittedAt` descending). There is currently no parameter to change sort order.
