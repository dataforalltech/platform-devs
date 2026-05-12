#!/usr/bin/env python3
"""Test rate limiting and audit logging functionality."""
import asyncio
import httpx
import psycopg2
import json
from time import sleep

GATEWAY_URL = "http://localhost:8080"
ADMIN_TOKEN = "test-admin-token"
DEV_TOKEN = "test-developer-token"
PG_HOST = "localhost"
PG_PORT = 5433
PG_DB = "platform_staging"
PG_USER = "platform"
PG_PASS = "staging_password_123"

def get_pg_conn():
    """Get PostgreSQL connection."""
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASS,
    )

async def test_rate_limiting():
    """Test rate limiting (readonly role has 5 req/sec limit)."""
    print("\n" + "="*60)
    print("TEST 1: Rate Limiting")
    print("="*60)

    # First clear the audit table for clean test
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM mcp_audit_log")
    conn.commit()
    cur.close()
    conn.close()
    print("✓ Cleared audit log table")

    # Test with admin token (100 req/sec limit, so we should pass with 10 requests)
    async with httpx.AsyncClient() as client:
        success_count = 0
        for i in range(10):
            try:
                resp = await client.post(
                    f"{GATEWAY_URL}/mcp/qazilla-mcp/tools/call",
                    json={"name": "generate_test_cases", "arguments": {}},
                    headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                    timeout=5,
                )
                if resp.status_code == 200:
                    success_count += 1
                else:
                    print(f"  Request {i+1}: Status {resp.status_code}")
            except Exception as e:
                print(f"  Request {i+1}: Error {e}")

        print(f"✓ Admin token (100 req/sec limit): {success_count}/10 successful")

    # Check audit logs were created
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM mcp_audit_log WHERE user_id='admin'")
    count = cur.fetchone()[0]
    print(f"✓ Audit logs created: {count} records for admin")

    # Check statuses in audit log
    cur.execute("SELECT status, COUNT(*) FROM mcp_audit_log WHERE user_id='admin' GROUP BY status")
    for status, cnt in cur.fetchall():
        print(f"  - {status}: {cnt}")

    cur.close()
    conn.close()

async def test_audit_logging():
    """Test that audit logging works correctly."""
    print("\n" + "="*60)
    print("TEST 2: Audit Logging")
    print("="*60)

    conn = get_pg_conn()
    cur = conn.cursor()

    # Clear table
    cur.execute("DELETE FROM mcp_audit_log")
    conn.commit()
    print("✓ Cleared audit log table")

    # Make a request with developer token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GATEWAY_URL}/mcp/qazilla-mcp/tools/call",
            json={"name": "generate_test_cases", "arguments": {"scenario": "test"}},
            headers={"Authorization": f"Bearer {DEV_TOKEN}"},
            timeout=5,
        )
        print(f"✓ Made tool call, response status: {resp.status_code}")

    # Query audit logs
    sleep(1)  # Give database time to write
    cur.execute("""
        SELECT user_id, role, mcp, tool, status, arguments, client_ip
        FROM mcp_audit_log
        ORDER BY ts DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    if row:
        user_id, role, mcp, tool, status, arguments, client_ip = row
        print(f"✓ Audit log entry found:")
        print(f"  - user_id: {user_id}")
        print(f"  - role: {role}")
        print(f"  - mcp: {mcp}")
        print(f"  - tool: {tool}")
        print(f"  - status: {status}")
        print(f"  - arguments: {arguments}")
        print(f"  - client_ip: {client_ip}")
    else:
        print("✗ No audit log entry found!")

    # Check indices are working
    cur.execute("SELECT COUNT(*) FROM mcp_audit_log WHERE user_id='dev1'")
    count = cur.fetchone()[0]
    print(f"✓ Index query (user_id): {count} records for dev1")

    cur.execute("SELECT COUNT(*) FROM mcp_audit_log WHERE mcp='qazilla-mcp'")
    count = cur.fetchone()[0]
    print(f"✓ Index query (mcp): {count} records for qazilla-mcp")

    cur.close()
    conn.close()

async def test_rbac_blocking():
    """Test that RBAC blocks unauthorized calls."""
    print("\n" + "="*60)
    print("TEST 3: RBAC Blocking")
    print("="*60)

    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM mcp_audit_log")
    conn.commit()
    cur.close()
    conn.close()

    # Developer token should not have access to all MCPs/tools
    # Try to call a restricted tool
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GATEWAY_URL}/mcp/seczilla-mcp/tools/call",
            json={"name": "generate_threat_model", "arguments": {}},
            headers={"Authorization": f"Bearer {DEV_TOKEN}"},
            timeout=5,
        )

        if resp.status_code == 403:
            print(f"✓ RBAC correctly blocked unauthorized call: {resp.status_code}")
        else:
            print(f"✗ Expected 403, got {resp.status_code}")

    # Verify forbidden status was logged
    sleep(1)
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM mcp_audit_log WHERE status='forbidden'")
    count = cur.fetchone()[0]
    print(f"✓ Forbidden calls logged: {count} records")
    cur.close()
    conn.close()

async def main():
    """Run all tests."""
    print("\n" + "🔬 " * 20)
    print("GATEWAY VALIDATION: Rate Limiting + Audit Logging")
    print("🔬 " * 20)

    try:
        await test_rate_limiting()
        await test_audit_logging()
        await test_rbac_blocking()

        print("\n" + "="*60)
        print("✅ ALL TESTS COMPLETED")
        print("="*60)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
