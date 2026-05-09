"""MCP server implementation for platform-cache."""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import Settings
from ..tools import cache_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()
server = Server("cache-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="cache_health_check",
            description="Check if platform-cache service is healthy",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="cache_set",
            description="Set a cache key-value pair with optional TTL",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The cache key",
                    },
                    "value": {
                        "type": "string",
                        "description": "The value to cache",
                    },
                    "ttl": {
                        "type": "integer",
                        "description": "Time-to-live in seconds (optional)",
                    },
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="cache_get",
            description="Get a value from cache by key",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The cache key",
                    }
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="cache_delete",
            description="Delete a key from cache",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The cache key to delete",
                    }
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="cache_clear_all",
            description="Clear all cache entries",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="cache_get_stats",
            description="Get cache hit/miss statistics",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="cache_set_pattern",
            description="Set multiple cache keys with a pattern prefix",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern prefix for all keys (e.g., 'user:123:*')",
                    },
                    "values": {
                        "type": "object",
                        "description": "Dictionary of key suffixes to values",
                    },
                    "ttl": {
                        "type": "integer",
                        "description": "Time-to-live in seconds (optional, applied to all keys)",
                    },
                },
                "required": ["pattern", "values"],
            },
        ),
        Tool(
            name="cache_increment",
            description="Atomically increment a numeric cache value",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The cache key",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Amount to increment (default 1)",
                    },
                },
                "required": ["key"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> Any:
    """Handle tool calls."""
    try:
        if name == "cache_health_check":
            return await cache_tools.cache_health_check()
        elif name == "cache_set":
            return await cache_tools.cache_set(
                key=arguments.get("key"),
                value=arguments.get("value"),
                ttl=arguments.get("ttl"),
            )
        elif name == "cache_get":
            return await cache_tools.cache_get(key=arguments.get("key"))
        elif name == "cache_delete":
            return await cache_tools.cache_delete(key=arguments.get("key"))
        elif name == "cache_clear_all":
            return await cache_tools.cache_clear_all()
        elif name == "cache_get_stats":
            return await cache_tools.cache_get_stats()
        elif name == "cache_set_pattern":
            return await cache_tools.cache_set_pattern(
                pattern=arguments.get("pattern"),
                values=arguments.get("values"),
                ttl=arguments.get("ttl"),
            )
        elif name == "cache_increment":
            return await cache_tools.cache_increment(
                key=arguments.get("key"),
                amount=arguments.get("amount", 1),
            )
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "UnknownTool",
                            "details": f"Tool {name} is not recognized",
                        }
                    ),
                )
            ]
    except Exception as e:
        logger.exception(f"Error calling tool {name}")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "InternalError", "details": str(e)}),
            )
        ]


def main() -> None:
    """Run the MCP server."""
    asyncio.run(server.run(sys.stdin.buffer, sys.stdout.buffer))


if __name__ == "__main__":
    import sys

    main()
