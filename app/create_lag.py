"""
Demo script: Tạo replication lag rõ ràng để test patterns
Chạy script này TRƯỚC KHI test các patterns
"""

import psycopg2
import time

def create_replication_lag():
    """Insert massive data để tạo lag trên replicas"""
    print("=" * 60)
    print("CREATING REPLICATION LAG FOR PATTERN TESTING")
    print("=" * 60)
    
    # Connect to primary
    conn = psycopg2.connect(
        host="localhost", port=5432,
        database="testdb", user="postgres", password="postgres"
    )
    
    print("\n[Step 1] Inserting 500k rows to create lag...")
    start = time.time()
    
    with conn.cursor() as cur:
        # Bulk insert với large data
        cur.execute("""
            INSERT INTO replication_test (data)
            SELECT 
                'Large-Data-' || i || '-' || repeat('X', 500)
            FROM generate_series(1, 500000) i
        """)
        conn.commit()
    
    elapsed = time.time() - start
    print(f"✅ Insert completed in {elapsed:.2f}s")
    
    print("\n[Step 2] Checking replication lag...")
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                application_name,
                pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS lag_size,
                ROUND(EXTRACT(EPOCH FROM replay_lag)::numeric, 2) AS lag_sec
            FROM pg_stat_replication
        """)
        results = cur.fetchall()
    
    print("\nReplication Status:")
    print("-" * 60)
    for row in results:
        app_name, lag_size, lag_sec = row
        print(f"  {app_name}: {lag_size} lag ({lag_sec}s)")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("✅ Replication lag created successfully!")
    print("=" * 60)
    print("\nNow you can test the patterns:")
    print("  python app/pattern1_primary_routing.py")
    print("  python app/pattern2_lsn_tracking.py")
    print("  python app/pattern3_sticky_session.py")
    print("\n💡 Lag will gradually decrease as replicas catch up")


if __name__ == "__main__":
    create_replication_lag()
