"""
Pattern 2: LSN-Based Read Routing
- Track LSN after write
- Only read from replica if it has replayed to that LSN
"""

import psycopg2
from typing import Optional

class LSNTracker:
    def __init__(self):
        self.last_write_lsn: Optional[str] = None
    
    def record_write_lsn(self, conn):
        """Get current LSN after write"""
        with conn.cursor() as cur:
            cur.execute("SELECT pg_current_wal_lsn()")
            self.last_write_lsn = cur.fetchone()[0]
    
    def replica_is_caught_up(self, replica_conn) -> bool:
        """Check if replica has replayed to last write LSN"""
        if not self.last_write_lsn:
            return True  # No writes yet
        
        with replica_conn.cursor() as cur:
            cur.execute("SELECT pg_last_wal_replay_lsn()")
            replica_lsn = cur.fetchone()[0]
        
        # Compare LSNs
        with replica_conn.cursor() as cur:
            cur.execute(
                "SELECT %s <= %s",
                (self.last_write_lsn, replica_lsn)
            )
            is_caught_up = cur.fetchone()[0]
        
        return is_caught_up


class SmartDatabaseClient:
    def __init__(self):
        self.primary_conn = psycopg2.connect(
            host="localhost", port=5432,
            database="testdb", user="postgres", password="postgres"
        )
        self.replica_conn = psycopg2.connect(
            host="localhost", port=5433,
            database="testdb", user="postgres", password="postgres"
        )
        self.lsn_tracker = LSNTracker()
    
    def write_data(self, data: str):
        """Write to primary and track LSN"""
        with self.primary_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO replication_test (data) VALUES (%s) RETURNING id",
                (data,)
            )
            record_id = cur.fetchone()[0]
            self.primary_conn.commit()
        
        # Track LSN position after write
        self.lsn_tracker.record_write_lsn(self.primary_conn)
        
        print(f"✅ Write to PRIMARY: ID={record_id}")
        print(f"   LSN: {self.lsn_tracker.last_write_lsn}")
        return record_id
    
    def read_data(self, limit=5, prefer_replica=True):
        """Read with LSN-aware routing"""
        if prefer_replica and self.lsn_tracker.replica_is_caught_up(self.replica_conn):
            conn = self.replica_conn
            source = "REPLICA (caught up)"
        else:
            conn = self.primary_conn
            source = "PRIMARY (replica lagging)"
        
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, data, created_at FROM replication_test "
                "ORDER BY id DESC LIMIT %s",
                (limit,)
            )
            results = cur.fetchall()
        
        print(f"📖 Read from {source}: {len(results)} rows")
        return results
    
    def close(self):
        self.primary_conn.close()
        self.replica_conn.close()


def test_pattern2():
    """Test LSN-based routing"""
    print("=" * 60)
    print("PATTERN 2: LSN-Based Read Routing")
    print("=" * 60)
    
    client = SmartDatabaseClient()
    
    # Test: Write → Read (should route intelligently)
    print("\n[Test] Write → Immediate Read with LSN check")
    client.write_data("Pattern2-LSN-Test")
    
    # First read might go to primary if replica hasn't caught up
    results = client.read_data(limit=3)
    
    # Second read likely from replica (LSN caught up in local env)
    import time
    time.sleep(0.1)  # Small delay
    results = client.read_data(limit=3)
    
    client.close()
    print("\n✅ Pattern 2 test completed!")


if __name__ == "__main__":
    test_pattern2()