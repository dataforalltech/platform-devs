# Platform Cache MCP

Model Context Protocol server for caching operations with Redis/Memcached backend support.

## Overview

The platform-cache-mcp provides a set of tools for managing cache operations including:
- Health checks and monitoring
- Key-value operations (set, get, delete)
- Bulk operations (pattern-based setting)
- Atomic operations (increment)
- Cache statistics and analytics

## Available Tools

### 1. cache_health_check
Check if the platform-cache service is healthy.

**Input:**
- No parameters required

**Output:**
- `status`: "ok" or error details
- `data`: Health status from the service

### 2. cache_set
Set a cache key-value pair with optional TTL.

**Input:**
- `key` (string, required): The cache key
- `value` (string, required): The value to cache
- `ttl` (integer, optional): Time-to-live in seconds

**Output:**
- Operation result with key and status

### 3. cache_get
Get a value from cache by key.

**Input:**
- `key` (string, required): The cache key

**Output:**
- `value`: The cached value
- Error if key not found (404)

### 4. cache_delete
Delete a key from cache.

**Input:**
- `key` (string, required): The cache key to delete

**Output:**
- `deleted`: Boolean indicating success
- Error if key not found (404)

### 5. cache_clear_all
Clear all cache entries.

**Input:**
- No parameters required

**Output:**
- `cleared`: Boolean indicating success
- `entries`: Number of entries cleared

### 6. cache_get_stats
Get cache hit/miss statistics.

**Input:**
- No parameters required

**Output:**
- `hits`: Number of cache hits
- `misses`: Number of cache misses
- `hit_rate`: Hit rate percentage

### 7. cache_set_pattern
Set multiple cache keys with a pattern prefix.

**Input:**
- `pattern` (string, required): Pattern prefix for all keys (e.g., "user:123:*")
- `values` (object, required): Dictionary of key suffixes to values
- `ttl` (integer, optional): Time-to-live in seconds (applied to all keys)

**Output:**
- `pattern`: The pattern used
- `set_count`: Number of keys set

### 8. cache_increment
Atomically increment a numeric cache value.

**Input:**
- `key` (string, required): The cache key
- `amount` (integer, optional): Amount to increment (default 1)

**Output:**
- `key`: The key that was incremented
- `value`: The new value
- Error if key not found (404) or invalid (400)

## Configuration

Environment variables (prefix: `MCP_CACHE_`):
- `MCP_CACHE_BASE_URL`: Base URL of the platform-cache API (default: http://localhost:8025)
- `MCP_CACHE_INTERNAL_TOKEN`: X-Internal-Token for service-to-service authentication
- `MCP_CACHE_LOG_LEVEL`: Logging level (default: INFO)
- `MCP_CACHE_REQUEST_TIMEOUT`: HTTP request timeout in seconds (default: 30.0)

## Testing

Run tests with coverage:
```bash
pytest --cov=src --cov-report=term-missing
```

Expected coverage: ≥80%
Expected test count: 37+

## Architecture

```
src/
├── config/
│   └── settings.py       # Pydantic settings with env_prefix=MCP_CACHE_
├── client/
│   └── api_client.py     # Async HTTP client for platform-cache API
├── server/
│   └── mcp_server.py     # MCP server implementation
└── tools/
    └── cache_tools.py    # 8 cache operation tools
```

## Error Handling

All tools implement comprehensive error handling:
- HTTP errors (400, 404, 500): Specific error messages
- Exceptions: Generic "InternalError" with details
- All errors returned as JSON in MCP TextContent format

## Service Integration

Integrates with:
- platform-cache backend API at `MCP_CACHE_BASE_URL`
- Uses internal token for authentication
- Timeout configurable per request

## Version

1.0.0 (Phase 4c - Caching Infrastructure)
