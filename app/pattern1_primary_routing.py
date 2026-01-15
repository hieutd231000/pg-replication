"""
Pattern 1: Read-Your-Writes via Primary Routing
- Track last write timestamp per session
- Route reads to primary if < threshold seconds
"""

import psycopg2
from datetime import datetime, timedelta
from typing import Optional

class SessionTracker:
    def __init__(self):
        self.last_write_time: Optional[datetime] = None
        self.write_threshold_seconds = 5  # Route to primary for 5s after write
    
    def record_write(self):
        """Called after every write operation"""
        self.last_write_time = datetime.now()
    
    def should_read_from_primary(self) -> bool:
        """Check if we should route read to primary"""
        if not self.last_write_time:
            return False
        
        elapsed = (datetime.now() - self.last_write_time).total_seconds()
        return elapsed < self.write_threshold_seconds


class DatabaseClient:
    def __init__(self):
        self.primary_conn = psycopg2.connect(
            host="localhost", port=5432, 
            database="testdb", user="postgres", password="postgres"
        )
        self.replica_conn = psycopg2.connect(
            host="localhost", port=5433,  # replica1
            database="testdb", user="postgres", password="postgres"
        )
        self.session = SessionTracker()
    
    def write_data(self, data: str):
        """Write always goes to primary"""
        with self.primary_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO replication_test (data) VALUES (%s) RETURNING id",
                (data,)
            )
            record_id = cur.fetchone()[0]
            self.primary_conn.commit()
            
            # Track write time
            self.session.record_write()
            
            print(f"✅ Written to PRIMARY: ID={record_id}, data='{data}'")
            return record_id
    
    def read_data(self, limit=5):
        """Smart routing based on write history"""
        if self.session.should_read_from_primary():
            conn = self.primary_conn
            source = "PRIMARY (recent write)"
        else:
            conn = self.replica_conn
            source = "REPLICA"
        
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


def test_pattern1():
    """Test read-your-writes with primary routing"""
    print("=" * 60)
    print("PATTERN 1: Read-Your-Writes via Primary Routing")
    print("=" * 60)
    
    client = DatabaseClient()
    
    # Setup: Create artificial lag with bulk insert
    print("\n[Setup] Creating replication lag...")
    print("Inserting 100k rows to create lag on replicas...")
    with client.primary_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO replication_test (data) "
            "SELECT 'Lag-' || generate_series(1, 100000)"
        )
        client.primary_conn.commit()
    
    print("✅ Bulk insert done. Replicas catching up in background...")
    
    import time
    time.sleep(0.5)  # Small delay
    
    # Scenario 1: Write then immediate read (during lag)
    print("\n" + "=" * 60)
    print("[Test 1] Write → Immediate Read (during replication lag)")
    print("=" * 60)
    
    test_id = client.write_data("Pattern1-Critical-Data")
    
    # Immediate read - should go to PRIMARY
    print("\n⏱️  Immediate read (< 5s, should route to PRIMARY):")
    results = client.read_data(limit=3)
    
    # Verify on replica directly
    print("\n🔍 Checking replica directly:")
    with client.replica_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM replication_test WHERE data = 'Pattern1-Critical-Data'"
        )
        replica_count = cur.fetchone()[0]
    
    if replica_count == 0:
        print("   ⚠️  Replica DOES NOT have data yet (lag exists!)")
        print("   ✅ Pattern working: Read went to PRIMARY to ensure consistency")
    else:
        print("   ✅ Replica already has data (replication very fast on local)")
        print("   Note: On local Docker, replication is too fast to see lag")
    
    # Scenario 2: Wait > threshold, then read
    print("\n" + "=" * 60)
    print("[Test 2] Write → Wait 6s → Read from REPLICA")
    print("=" * 60)
    
    test_id2 = client.write_data("Pattern1-After-Wait")
    print("\n⏳ Waiting 6 seconds for threshold to pass...")
    time.sleep(6)
    
    print("\n⏱️  Read after 6s (should route to REPLICA):")
    results = client.read_data(limit=3)
    
    client.close()
    
    print("\n" + "=" * 60)
    print("✅ Pattern 1 test completed!")
    print("=" * 60)
    
    print("\n💡 To see CLEARER lag effects (recommended):")
    print("\n   Method 1: Stop replica before test")
    print("   -" * 30)
    print("   docker stop pg-replica1")
    print("   python app/pattern1_primary_routing.py")
    print("   # Observe: ALL reads go to PRIMARY")
    print("   docker start pg-replica1")
    
    print("\n   Method 2: Network throttling")
    print("   -" * 30)
    print("   docker exec -it pg-replica1 bash -c \"")
    print("   apt-get update && apt-get install -y iproute2")
    print("   tc qdisc add dev eth0 root netem delay 200ms\"")
    print("   python app/pattern1_primary_routing.py")
    print("   # Observe: Reads go to PRIMARY when lag > 0")
    
    print("\n   Then remove throttling:")
    print("   docker exec pg-replica1 tc qdisc del dev eth0 root")


if __name__ == "__main__":
    test_pattern1()