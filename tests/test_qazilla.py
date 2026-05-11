"""
Unit tests for qazilla-mcp (Quality Assurance Zilla)
Tests CRUD operations for test plans, test cases, and validations
"""
import pytest
import json
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def db_connection():
    """Connect to test PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            user="postgres",
            password="postgres_password_local_dev",
            database="app",
            connect_timeout=5
        )
        yield conn
        conn.close()
    except psycopg2.OperationalError:
        pytest.skip("PostgreSQL not available (localhost:5432)")


@pytest.fixture(autouse=True)
def setup_teardown_db(db_connection):
    """Create/cleanup test data before each test"""
    cursor = db_connection.cursor()

    # Verify schema exists (don't create, assume it's already there)
    cursor.execute("""
        SELECT EXISTS(
            SELECT FROM information_schema.tables
            WHERE table_name = 'test_plans'
        )
    """)
    if not cursor.fetchone()[0]:
        pytest.skip("PostgreSQL schema not initialized (run db/create_zilla_tables.sql)")

    db_connection.commit()
    yield

    # Cleanup after each test (handle aborted transactions)
    try:
        db_connection.rollback()  # Reset any failed transaction
        cursor.execute("DELETE FROM test_cases WHERE title LIKE 'test_%' OR title LIKE 'concurrent_%' OR title LIKE 'perf_test_%' OR title LIKE 'query_test_%'")
        cursor.execute("DELETE FROM test_plans WHERE title LIKE 'test_%' OR title LIKE 'concurrent_%' OR title LIKE 'perf_test_%' OR title LIKE 'query_test_%'")
        db_connection.commit()
    except Exception as e:
        db_connection.rollback()
    finally:
        cursor.close()


# ============================================================================
# Unit Tests
# ============================================================================

def test_insert_test_plan(db_connection):
    """Test: Insert a valid test plan"""
    cursor = db_connection.cursor()

    plan_id = f"tp_{datetime.now().isoformat()}"
    cursor.execute("""
        INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        plan_id,
        "test_login_flow",
        "Authentication",
        "Login endpoint",
        "Validate login success/failure",
        "draft",
        datetime.now(),
        datetime.now()
    ))
    db_connection.commit()

    # Verify insertion
    cursor.execute("SELECT title, feature FROM test_plans WHERE id = %s", (plan_id,))
    row = cursor.fetchone()

    assert row is not None
    assert row[0] == "test_login_flow"
    assert row[1] == "Authentication"


def test_select_test_plan(db_connection):
    """Test: Retrieve a test plan by ID"""
    cursor = db_connection.cursor(cursor_factory=RealDictCursor)

    plan_id = f"tp_{datetime.now().isoformat()}"
    cursor.execute("""
        INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        plan_id,
        "test_api_crud",
        "API",
        "CRUD endpoints",
        "Validate all CRUD operations",
        "draft",
        datetime.now(),
        datetime.now()
    ))
    db_connection.commit()

    # Retrieve
    cursor.execute("SELECT * FROM test_plans WHERE id = %s", (plan_id,))
    plan = cursor.fetchone()

    assert plan["id"] == plan_id
    assert plan["title"] == "test_api_crud"
    assert plan["status"] == "draft"


def test_update_test_plan(db_connection):
    """Test: Update test plan status"""
    cursor = db_connection.cursor()

    plan_id = f"tp_{datetime.now().isoformat()}"
    cursor.execute("""
        INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        plan_id,
        "test_update",
        "Feature",
        "Scope",
        "Objectives",
        "draft",
        datetime.now(),
        datetime.now()
    ))

    # Update status
    cursor.execute("""
        UPDATE test_plans SET status = %s, updated_at = %s WHERE id = %s
    """, ("ready", datetime.now(), plan_id))
    db_connection.commit()

    # Verify update
    cursor.execute("SELECT status FROM test_plans WHERE id = %s", (plan_id,))
    new_status = cursor.fetchone()[0]

    assert new_status == "ready"


def test_delete_test_plan(db_connection):
    """Test: Delete a test plan"""
    cursor = db_connection.cursor()

    plan_id = f"tp_{datetime.now().isoformat()}"
    cursor.execute("""
        INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        plan_id,
        "test_delete",
        "Feature",
        "Scope",
        "Objectives",
        "draft",
        datetime.now(),
        datetime.now()
    ))
    db_connection.commit()

    # Delete
    cursor.execute("DELETE FROM test_plans WHERE id = %s", (plan_id,))
    db_connection.commit()

    # Verify deletion
    cursor.execute("SELECT COUNT(*) FROM test_plans WHERE id = %s", (plan_id,))
    count = cursor.fetchone()[0]

    assert count == 0


def test_list_test_plans_with_pagination(db_connection):
    """Test: List test plans with pagination"""
    cursor = db_connection.cursor()

    # Insert 25 test plans
    for i in range(25):
        plan_id = f"tp_test_{i}"
        cursor.execute("""
            INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            plan_id,
            f"test_plan_{i}",
            "Feature",
            "Scope",
            "Objectives",
            "draft",
            datetime.now(),
            datetime.now()
        ))
    db_connection.commit()

    # Get page 1
    cursor.execute("""
        SELECT * FROM test_plans WHERE title LIKE 'test_plan_%' ORDER BY created_at LIMIT 10 OFFSET 0
    """)
    page1 = cursor.fetchall()

    # Get page 2
    cursor.execute("""
        SELECT * FROM test_plans WHERE title LIKE 'test_plan_%' ORDER BY created_at LIMIT 10 OFFSET 10
    """)
    page2 = cursor.fetchall()

    assert len(page1) == 10
    assert len(page2) == 10
    assert page1[0][0] != page2[0][0]  # Different IDs


def test_concurrent_inserts_no_corruption(db_connection):
    """Test: Multiple concurrent inserts don't cause data loss"""
    import concurrent.futures
    import uuid

    def insert_plan(i):
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            user="postgres",
            password="postgres_password_local_dev",
            database="app"
        )
        cursor = conn.cursor()
        plan_id = f"tp_{uuid.uuid4()}"
        cursor.execute("""
            INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            plan_id,
            f"concurrent_{i}",
            "Feature",
            "Scope",
            "Objectives",
            "draft",
            datetime.now(),
            datetime.now()
        ))
        conn.commit()
        conn.close()
        return plan_id

    # Run 20 concurrent inserts
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(insert_plan, range(20)))

    # Verify all inserts succeeded
    cursor = db_connection.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM test_plans WHERE title LIKE 'concurrent_%'
    """)
    count = cursor.fetchone()[0]

    assert len(results) == 20
    assert count == 20  # No lost inserts


def test_insert_with_null_title_fails(db_connection):
    """Test: Cannot insert test plan with NULL title"""
    cursor = db_connection.cursor()

    with pytest.raises(psycopg2.IntegrityError):
        cursor.execute("""
            INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
            VALUES (%s, NULL, %s, %s, %s, %s, %s, %s)
        """, (
            "tp_test",
            "Feature",
            "Scope",
            "Objectives",
            "draft",
            datetime.now(),
            datetime.now()
        ))
        db_connection.commit()


def test_plan_status_lifecycle(db_connection):
    """Test: Test plan follows expected status transitions"""
    cursor = db_connection.cursor()

    plan_id = f"tp_lifecycle_{datetime.now().isoformat()}"

    # Create in draft
    cursor.execute("""
        INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        plan_id,
        "test_lifecycle",
        "Feature",
        "Scope",
        "Objectives",
        "draft",
        datetime.now(),
        datetime.now()
    ))
    db_connection.commit()

    # Transition: draft → ready
    cursor.execute("""UPDATE test_plans SET status = %s WHERE id = %s""", ("ready", plan_id))
    db_connection.commit()

    cursor.execute("SELECT status FROM test_plans WHERE id = %s", (plan_id,))
    assert cursor.fetchone()[0] == "ready"

    # Transition: ready → in_progress
    cursor.execute("""UPDATE test_plans SET status = %s WHERE id = %s""", ("in_progress", plan_id))
    db_connection.commit()

    cursor.execute("SELECT status FROM test_plans WHERE id = %s", (plan_id,))
    assert cursor.fetchone()[0] == "in_progress"

    # Transition: in_progress → completed
    cursor.execute("""UPDATE test_plans SET status = %s WHERE id = %s""", ("completed", plan_id))
    db_connection.commit()

    cursor.execute("SELECT status FROM test_plans WHERE id = %s", (plan_id,))
    assert cursor.fetchone()[0] == "completed"


# ============================================================================
# Integration Tests (DB + API interaction)
# ============================================================================

def test_create_test_case_for_plan(db_connection):
    """Test: Create test case linked to test plan"""
    cursor = db_connection.cursor()

    # First create a test plan
    plan_id = f"tp_{datetime.now().isoformat()}"
    cursor.execute("""
        INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        plan_id,
        "test_parent_plan",
        "Feature",
        "Scope",
        "Objectives",
        "draft",
        datetime.now(),
        datetime.now()
    ))
    db_connection.commit()

    # Then create a test case linked to it
    case_id = f"tc_{datetime.now().isoformat()}"
    cursor.execute("""
        INSERT INTO test_cases (id, plan_id, title, type, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        case_id,
        plan_id,
        "test_case_1",
        "positive",
        datetime.now()
    ))
    db_connection.commit()

    # Verify relationship
    cursor.execute("""
        SELECT tc.title, tp.title FROM test_cases tc
        JOIN test_plans tp ON tc.plan_id = tp.id
        WHERE tc.id = %s
    """, (case_id,))

    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "test_case_1"
    assert row[1] == "test_parent_plan"


# ============================================================================
# Performance Tests
# ============================================================================

def test_insert_performance_1000_records(db_connection):
    """Test: Bulk insert 1000 test plans (< 5 seconds)"""
    import time

    cursor = db_connection.cursor()
    start = time.time()

    for i in range(1000):
        plan_id = f"tp_perf_{i}"
        cursor.execute("""
            INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            plan_id,
            f"perf_test_{i}",
            "Feature",
            "Scope",
            "Objectives",
            "draft",
            datetime.now(),
            datetime.now()
        ))

    db_connection.commit()
    elapsed = time.time() - start

    # Should complete in < 5 seconds
    assert elapsed < 5.0, f"Bulk insert took {elapsed:.2f}s, expected < 5s"

    # Verify all inserted
    cursor.execute("SELECT COUNT(*) FROM test_plans WHERE title LIKE 'perf_test_%'")
    count = cursor.fetchone()[0]
    assert count == 1000


def test_query_performance_with_limit(db_connection):
    """Test: Query with LIMIT 100 is fast (< 100ms)"""
    import time

    cursor = db_connection.cursor()

    # Ensure we have data
    for i in range(500):
        plan_id = f"tp_query_{i}"
        cursor.execute("""
            INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            plan_id,
            f"query_test_{i}",
            "Feature",
            "Scope",
            "Objectives",
            "draft",
            datetime.now(),
            datetime.now()
        ))
    db_connection.commit()

    # Time the query
    start = time.time()
    cursor.execute("""
        SELECT * FROM test_plans WHERE title LIKE 'query_test_%' LIMIT 100
    """)
    results = cursor.fetchall()
    elapsed = time.time() - start

    # Should complete in < 100ms
    assert elapsed < 0.1, f"Query took {elapsed:.3f}s, expected < 0.1s"
    assert len(results) == 100
