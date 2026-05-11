#!/usr/bin/env python3
"""
MCP Registry - Service Discovery for all MCPs
Discovers and aggregates all available MCPs on the network
Port: 8000
"""
import os
import asyncio
import aiohttp
from fastapi import FastAPI
from typing import List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MCP Registry",
    description="Service discovery and registry for all MCPs",
    version="1.0.0"
)

# MCP Service Definitions
MCP_SERVICES = {
    # System MCPs
    "config-mcp": {"host": "config-mcp", "port": 7100, "type": "system"},
    "agent-twin-mcp": {"host": "agent-twin-mcp", "port": 7101, "type": "system"},
    "session-mcp": {"host": "session-mcp", "port": 7102, "type": "system"},
    "auth-mcp": {"host": "auth-mcp", "port": 7103, "type": "system"},
    "admin-mcp": {"host": "admin-mcp", "port": 7104, "type": "system"},
    "audit-mcp": {"host": "audit-mcp", "port": 7105, "type": "system"},
    "infra-mcp": {"host": "infra-mcp", "port": 7106, "type": "system"},
    "services-mcp": {"host": "services-mcp", "port": 7107, "type": "system"},
    "pipeline-mcp": {"host": "pipeline-mcp", "port": 7108, "type": "system"},
    "qa-mcp": {"host": "qa-mcp", "port": 7109, "type": "system"},
    "deploy-mcp": {"host": "deploy-mcp", "port": 7110, "type": "system"},
    "docs-mcp": {"host": "docs-mcp", "port": 7111, "type": "system"},
    "ai-governance-mcp": {"host": "ai-governance-mcp", "port": 7112, "type": "system"},
    "governance-mcp": {"host": "governance-mcp", "port": 7113, "type": "system"},
    "scheduler-mcp": {"host": "scheduler-mcp", "port": 7114, "type": "system"},
    "connectors-mcp": {"host": "connectors-mcp", "port": 7115, "type": "system"},
    "cache-mcp": {"host": "cache-mcp", "port": 7116, "type": "system"},
    "test-mcp": {"host": "test-mcp", "port": 7117, "type": "system"},

    # Zilla MCPs
    "archzilla-mcp": {"host": "archzilla-mcp", "port": 7100, "type": "zilla"},
    "backzilla-mcp": {"host": "backzilla-mcp", "port": 7100, "type": "zilla"},
    "frontzilla-mcp": {"host": "frontzilla-mcp", "port": 7100, "type": "zilla"},
    "opszilla-mcp": {"host": "opszilla-mcp", "port": 7100, "type": "zilla"},
    "pozilla-mcp": {"host": "pozilla-mcp", "port": 7100, "type": "zilla"},
    "productzilla-mcp": {"host": "productzilla-mcp", "port": 7100, "type": "zilla"},
    "qazilla-mcp": {"host": "qazilla-mcp", "port": 7100, "type": "zilla"},
    "seczilla-mcp": {"host": "seczilla-mcp", "port": 7100, "type": "zilla"},
}


class MCPRegistry:
    def __init__(self):
        self.services: Dict[str, Dict[str, Any]] = {}
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 30  # seconds

    async def discover_mcp(self, name: str, config: Dict[str, str]) -> Dict[str, Any]:
        """Discover a single MCP by calling its /info endpoint"""
        url = f"http://{config['host']}:{config['port']}/info"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        tools_count = info.get("tools", 0)

                        return {
                            "name": name,
                            "status": "online",
                            "url": f"http://{config['host']}:{config['port']}",
                            "type": config.get("type", "unknown"),
                            "tools": tools_count,
                            "version": info.get("version", "unknown"),
                            "description": info.get("description", "")
                        }
        except asyncio.TimeoutError:
            logger.warning(f"Timeout connecting to {name}")
        except Exception as e:
            logger.warning(f"Error discovering {name}: {e}")

        return {
            "name": name,
            "status": "offline",
            "url": f"http://{config['host']}:{config['port']}",
            "type": config.get("type", "unknown"),
            "tools": 0,
            "error": "Connection failed"
        }

    async def discover_all(self):
        """Discover all MCPs in parallel"""
        tasks = [
            self.discover_mcp(name, config)
            for name, config in MCP_SERVICES.items()
        ]
        results = await asyncio.gather(*tasks)

        for result in results:
            self.services[result["name"]] = result

    async def ensure_discovered(self):
        """Lazy discovery on first access"""
        if not self.services:
            await self.discover_all()


registry = MCPRegistry()


# ============================================================================
# HTTP Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "mcp-registry",
        "version": "1.0",
        "endpoints": {
            "health": "/health",
            "services": "/services",
            "services/{name}": "/services/{name}",
            "stats": "/stats"
        }
    }


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy", "service": "mcp-registry"}


@app.get("/services")
async def list_services():
    """List all MCPs and their status"""
    await registry.ensure_discovered()

    return {
        "total": len(registry.services),
        "online": sum(1 for s in registry.services.values() if s["status"] == "online"),
        "offline": sum(1 for s in registry.services.values() if s["status"] == "offline"),
        "services": list(registry.services.values())
    }


@app.get("/services/{name}")
async def get_service(name: str):
    """Get details of a specific MCP"""
    await registry.ensure_discovered()

    if name not in registry.services:
        return {"error": f"Service {name} not found"}

    return registry.services[name]


@app.get("/services/type/{mcp_type}")
async def list_by_type(mcp_type: str):
    """List MCPs by type (system or zilla)"""
    await registry.ensure_discovered()

    services = [
        s for s in registry.services.values()
        if s.get("type") == mcp_type
    ]

    return {
        "type": mcp_type,
        "count": len(services),
        "services": services
    }


@app.get("/stats")
async def stats():
    """Service statistics"""
    await registry.ensure_discovered()

    online_services = [s for s in registry.services.values() if s["status"] == "online"]
    total_tools = sum(s.get("tools", 0) for s in online_services)

    return {
        "total_services": len(registry.services),
        "online_services": len(online_services),
        "offline_services": len(registry.services) - len(online_services),
        "total_tools": total_tools,
        "system_mcps": sum(1 for s in online_services if s["type"] == "system"),
        "zilla_mcps": sum(1 for s in online_services if s["type"] == "zilla")
    }


@app.post("/services/discover")
async def trigger_discovery():
    """Manually trigger service discovery"""
    await registry.discover_all()
    return {"message": "Discovery complete", "services_found": len(registry.services)}


@app.get("/config")
async def get_config():
    """Return configuration for Claude Code .mcp.json"""
    await registry.ensure_discovered()

    mcps = {}
    for name, service in registry.services.items():
        if service["status"] == "online":
            mcps[name] = {
                "command": "curl",
                "args": ["-X", "POST", f"{service['url']}/mcp/tools/call"],
                "url": service["url"]
            }

    return {
        "description": "Auto-generated MCP configuration from registry",
        "mcpServers": mcps
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting MCP Registry on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
