---
title: API Documentation Guide
author: Engineering Team
date: 2025-01-15
---

# API Documentation Guide

This guide covers the REST API endpoints for the Onyx platform.

## Authentication

All API requests require a valid bearer token in the Authorization header.

```bash
curl -H "Authorization: Bearer <token>" https://api.example.com/v1/search
```

## Endpoints

### Search

Perform a semantic search across indexed documents.

**URL:** `POST /api/search`

**Parameters:**
- `query` (string, required): Search query
- `filters` (object, optional): Document filters
- `top_k` (integer, optional): Number of results

**Response:**
```json
{
  "results": [
    {
      "document_id": "doc_123",
      "score": 0.95,
      "content": "..."
    }
  ]
}
```

### Index Document

Index a new document into the search corpus.

**URL:** `POST /api/index`

## Rate Limits

| Tier        | Requests/min | Burst |
|-------------|-------------|-------|
| Free        | 60          | 10    |
| Pro         | 600         | 100   |
| Enterprise  | Unlimited   | 500   |

For more details, visit [our docs](https://docs.example.com) or contact **support@example.com**.
