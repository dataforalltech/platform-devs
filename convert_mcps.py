#!/usr/bin/env python3
"""Converter MCPs to hybrid mode (stdio + HTTP)."""

import re
import sys
from pathlib import Path

MCPS = [
    "session-mcp",
    "audit-mcp",
    "deploy-mcp",
    "docs-mcp",
    "infra-mcp",
    "pipeline-mcp",
    "qa-mcp",
    "services-mcp",
    "test-mcp",
    "ai-governance-mcp",
]

def convert_mcp_server(mcp_name: str) -> bool:
    """Convert mcp_server.py to hybrid mode."""
    mcp_dir = Path(mcp_name + "-server")
    mcp_server = mcp_dir / "src" / "server" / "mcp_server.py"

    if not mcp_server.exists():
        print(f"  ✗ {mcp_server} not found")
        return False

    content = mcp_server.read_text()

    # Remove old threading imports and functions
    content = re.sub(
        r"import threading\n",
        "",
        content
    )

    content = re.sub(
        r"import uvicorn\nfrom fastapi import FastAPI\n",
        "from fastapi import FastAPI\n",
        content
    )

    # Remove old _start_http_api function
    content = re.sub(
        r"def _start_http_api\([^)]*\) -> None:[\s\S]*?thread\.start\(\)[\s\S]*?\n\n",
        "",
        content
    )

    # Add _build_http_app function before build_server
    build_server_match = re.search(r"^def build_server\(\)", content, re.MULTILINE)
    if build_server_match:
        insert_pos = build_server_match.start()
        build_http_app_code = '''def _build_http_app(store, settings) -> FastAPI:
    """Build FastAPI app for HTTP on port 7100."""
    app = FastAPI(title="{mcp_name} API", version="0.1.0", docs_url="/docs")
    if hasattr(store, '__dict__') and 'router' in dir(store.__class__):
        from ..api.router import make_router
        router = make_router(store, getattr(settings, 'api_token', None))
        app.include_router(router)
    return app


'''.format(mcp_name=mcp_name.replace("-mcp", "").replace("-", " ").title())

        content = content[:insert_pos] + build_http_app_code + content[insert_pos:]

    # Update build_server return statement to include http_app
    content = re.sub(
        r"(\s+)if settings\.api_enabled:\s*_start_http_api\([^)]*\)",
        r"\1http_app = _build_http_app(store, settings)",
        content
    )

    # Update build_server return type
    content = re.sub(
        r"def build_server\(\)[^:]*:",
        "def build_server() -> tuple[Any, SessionStore, SessionSettings, FastAPI]:",
        content
    )

    # Update return statement in build_server
    content = re.sub(
        r"return (server, [^,]+, [^)]+)",
        r"return \1, http_app",
        content
    )

    # Update _run function
    run_func = '''async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, _settings, _store, http_app = build_server()

    cfg = uvicorn.Config(
        http_app, host="0.0.0.0", port=7100,
        log_level="warning", access_log=False,
    )
    server_http = uvicorn.Server(cfg)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await asyncio.gather(
                server.run(read_stream, write_stream, server.create_initialization_options()),
                server_http.serve(),
            )
    except (EOFError, BrokenPipeError):
        pass
'''

    content = re.sub(
        r"async def _run\(\)[^:]*:[\s\S]*?server\.run\([^)]*\)\)",
        run_func.strip(),
        content
    )

    mcp_server.write_text(content)
    print(f"  ✓ Updated {mcp_server.relative_to(Path.cwd())}")
    return True


def convert_dockerfile(mcp_name: str) -> bool:
    """Convert Dockerfile to use pyproject.toml."""
    mcp_dir = Path(mcp_name + "-server")
    dockerfile = mcp_dir / "Dockerfile"

    if not dockerfile.exists():
        print(f"  ✗ {dockerfile} not found")
        return False

    new_content = f'''FROM python:3.11-slim
WORKDIR /app
COPY {mcp_name}-server/pyproject.toml .
COPY {mcp_name}-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7100
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD curl -f http://localhost:7100/health || exit 1
CMD ["{mcp_name}-server"]
'''

    dockerfile.write_text(new_content)
    print(f"  ✓ Updated {dockerfile.relative_to(Path.cwd())}")
    return True


def main():
    print("Converting MCPs to hybrid mode...\n")

    for mcp in MCPS:
        print(f"Converting {mcp}...")
        try:
            convert_mcp_server(mcp)
            convert_dockerfile(mcp)
        except Exception as e:
            print(f"  ✗ Error: {e}")
            continue

    print("\n✓ Conversion complete!")


if __name__ == "__main__":
    main()
