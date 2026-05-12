"""Audit logging middleware using PostgreSQL."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values

_conn = None

def get_connection():
    """Get or create PostgreSQL connection."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(
            host=os.getenv("PG_HOST", "postgres"),
            port=int(os.getenv("PG_PORT", "5432")),
            database=os.getenv("PG_DB", "platform_staging"),
            user=os.getenv("PG_USER", "platform"),
            password=os.getenv("PG_PASSWORD", "staging_password_123"),
            connect_timeout=5,
        )
    return _conn

def init_audit_table():
    """Create audit log table if it doesn't exist."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mcp_audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    ts TIMESTAMPTZ DEFAULT NOW(),
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    tenant_id TEXT,
                    mcp TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    arguments JSONB,
                    result JSONB,
                    duration_ms INTEGER,
                    status TEXT,
                    client_ip TEXT,
                    user_agent TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_audit_user_ts ON mcp_audit_log (user_id, ts);
                CREATE INDEX IF NOT EXISTS idx_audit_mcp_tool_ts ON mcp_audit_log (mcp, tool, ts);
            """)
            conn.commit()
            print("Audit table initialized successfully")
        except Exception as e:
            print(f"Error creating audit table: {e}")
            conn.rollback()
        finally:
            cur.close()
    except Exception as e:
        print(f"Warning: Could not initialize audit table: {e}")
        print("Audit logging will be disabled")

async def log_tool_call(
    user_id: str,
    role: str,
    tenant_id: str,
    mcp: str,
    tool: str,
    arguments: dict,
    result: dict | str,
    duration_ms: int,
    status: str,
    client_ip: str,
    user_agent: str,
):
    """Log a tool call to PostgreSQL audit table."""
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO mcp_audit_log
            (user_id, role, tenant_id, mcp, tool, arguments, result, duration_ms, status, client_ip, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            role,
            tenant_id,
            mcp,
            tool,
            json.dumps(arguments),
            json.dumps(result) if isinstance(result, dict) else result,
            duration_ms,
            status,
            client_ip,
            user_agent,
        ))

        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error logging to audit table: {e}")

def close_connection():
    """Close PostgreSQL connection."""
    global _conn
    if _conn and not _conn.closed:
        _conn.close()
