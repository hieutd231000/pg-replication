# APPLICATION-LEVEL CONSISTENCY PATTERNS

## 🎯 Mục tiêu

Implement các patterns để giải quyết **Read-After-Write** và **Monotonic Reads** issues trong Python application.

---

## 📋 Prerequisites

```powershell
# Tạo virtual environment
cd d:\Project\replication
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install psycopg2-binary
```

---

## 🔧 Pattern 1: Read-Your-Writes with Primary Routing

### **Problem:**
User writes data → immediately reads → data chưa replicate → stale read!

### **Solution:**
Route reads to **PRIMARY** trong X giây sau khi user write.

### **Implementation:**

Create `app/pattern1_primary_routing.py`:

```python
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
```

### **How to test:**

```powershell
# Chạy test
python app/pattern1_primary_routing.py
```

**Expected output:**
```
Written to PRIMARY: ID=123, data='Pattern1-Test-1'
Read from PRIMARY (recent write): 3 rows
Result: Pattern1-Test-1

Written to PRIMARY: ID=124, data='Pattern1-Test-2'
Waiting 6 seconds...
Read from REPLICA: 3 rows
```

---

## 🔧 Pattern 2: LSN-Based Routing

### **Problem:**
Time-based routing không chính xác (replication có thể nhanh hơn threshold).

### **Solution:**
Track **LSN position** sau write, chỉ read từ replica nếu replica đã replay đến LSN đó.

### **Implementation:**

Create `app/pattern2_lsn_tracking.py`:

```python
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
```

### **How to test:**

```powershell
python app/pattern2_lsn_tracking.py
```

---

## 🔧 Pattern 3: Sticky Session Routing

### **Problem:**
Load balancer routes user randomly → đọc từ replicas khác nhau → Monotonic Reads violated.

### **Solution:**
**Session affinity** - user luôn đọc từ **cùng 1 replica**.

### **Implementation:**

Create `app/pattern3_sticky_session.py`:

```python
"""
Pattern 3: Sticky Session Routing
- Hash user_id to consistent replica
- Guarantees monotonic reads per user
"""

import psycopg2
import hashlib

class StickySessionRouter:
    def __init__(self):
        self.replicas = [
            {"host": "localhost", "port": 5433, "name": "replica1"},
            {"host": "localhost", "port": 5434, "name": "replica2"},
        ]
        self.primary = {"host": "localhost", "port": 5432}
        self.connections = {}
    
    def get_replica_for_user(self, user_id: str) -> dict:
        """Consistent hash to select replica"""
        hash_value = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        # hash_value % số_replica → chọn replica index
        # Output: Luôn trả về cùng 1 replica cho cùng user_id
        replica_index = hash_value % len(self.replicas)
        return self.replicas[replica_index]
    
    def get_connection(self, db_config: dict):
        """Get or create connection"""
        key = f"{db_config['host']}:{db_config['port']}"
        if key not in self.connections:
            self.connections[key] = psycopg2.connect(
                host=db_config['host'],
                port=db_config['port'],
                database="testdb",
                user="postgres",
                password="postgres"
            )
        return self.connections[key]
    
    def write_for_user(self, user_id: str, data: str):
        """Write always to primary"""
        conn = self.get_connection(self.primary)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO replication_test (data) VALUES (%s) RETURNING id",
                (f"User-{user_id}: {data}",)
            )
            record_id = cur.fetchone()[0]
            conn.commit()
        
        print(f"✅ User '{user_id}' wrote to PRIMARY: ID={record_id}")
        return record_id
    
    def read_for_user(self, user_id: str, limit=5):
        """Read from user's sticky replica"""
        replica = self.get_replica_for_user(user_id)
        conn = self.get_connection(replica)
        
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, data, created_at FROM replication_test "
                "WHERE data LIKE %s ORDER BY id DESC LIMIT %s",
                (f"User-{user_id}:%",limit,)
            )
            results = cur.fetchall()
        
        print(f"📖 User '{user_id}' read from {replica['name']}: {len(results)} rows")
        return results
    
    def close_all(self):
        for conn in self.connections.values():
            conn.close()


def test_pattern3():
    """Test sticky session routing"""
    print("=" * 60)
    print("PATTERN 3: Sticky Session Routing")
    print("=" * 60)
    
    router = StickySessionRouter()
    
    # Simulate 3 users
    users = ["alice", "bob", "charlie"]
    
    print("\n[Test 1] Each user writes and reads")
    for user in users:
        router.write_for_user(user, "Hello World")
        import time
        time.sleep(0.5)  # Allow replication
        results = router.read_for_user(user)
        print(f"  → {user} sees {len(results)} records\n")
    
    print("[Test 2] Verify consistency - multiple reads from same replica")
    for _ in range(3):
        results = router.read_for_user("alice")
        print(f"  Alice's read #{_+1}: {len(results)} rows from same replica")
    
    router.close_all()
    print("\n✅ Pattern 3 test completed!")


if __name__ == "__main__":
    test_pattern3()
```

### **How to test:**

```powershell
python app/pattern3_sticky_session.py
```

**Expected output:**
```
User 'alice' wrote to PRIMARY: ID=125
User 'alice' read from replica1: 1 rows

User 'bob' wrote to PRIMARY: ID=126
User 'bob' read from replica2: 1 rows

User 'charlie' wrote to PRIMARY: ID=127
User 'charlie' read from replica1: 1 rows

Alice's read #1: 1 rows from same replica
Alice's read #2: 1 rows from same replica
Alice's read #3: 1 rows from same replica
```

---

## 📊 Performance Comparison

Create `app/benchmark_patterns.py`:

```python
"""
Benchmark different consistency patterns
"""

import time
import psycopg2
from pattern1_primary_routing import DatabaseClient
from pattern2_lsn_tracking import SmartDatabaseClient
from pattern3_sticky_session import StickySessionRouter

def benchmark_pattern(name: str, test_func, iterations=100):
    """Measure latency for a pattern"""
    print(f"\n🔬 Benchmarking: {name}")
    
    start = time.time()
    for i in range(iterations):
        test_func(i)
    end = time.time()
    
    avg_latency = ((end - start) / iterations) * 1000  # ms
    print(f"   Avg latency: {avg_latency:.2f}ms per operation")
    return avg_latency

def test_pattern1_op(i):
    client = DatabaseClient()
    client.write_data(f"bench-p1-{i}")
    client.read_data(limit=1)
    client.close()

def test_pattern2_op(i):
    client = SmartDatabaseClient()
    client.write_data(f"bench-p2-{i}")
    client.read_data(limit=1)
    client.close()

def test_pattern3_op(i):
    router = StickySessionRouter()
    router.write_for_user(f"user{i % 10}", f"bench-{i}")
    router.read_for_user(f"user{i % 10}", limit=1)
    router.close_all()

def run_benchmarks():
    print("=" * 60)
    print("PERFORMANCE BENCHMARK")
    print("=" * 60)
    
    results = {}
    results['Pattern 1 (Time-based)'] = benchmark_pattern(
        "Pattern 1: Primary Routing", 
        test_pattern1_op, 
        iterations=20
    )
    
    results['Pattern 2 (LSN-based)'] = benchmark_pattern(
        "Pattern 2: LSN Tracking", 
        test_pattern2_op, 
        iterations=20
    )
    
    results['Pattern 3 (Sticky)'] = benchmark_pattern(
        "Pattern 3: Sticky Session", 
        test_pattern3_op, 
        iterations=20
    )
    
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for pattern, latency in results.items():
        print(f"{pattern}: {latency:.2f}ms")
    
    print("\n📝 Trade-offs:")
    print("• Pattern 1: Simple, but may route to primary unnecessarily")
    print("• Pattern 2: Most accurate, but LSN queries add overhead")
    print("• Pattern 3: Best for monotonic reads, load balanced")

if __name__ == "__main__":
    run_benchmarks()
```

---

## 🎯 Testing Workflow

### **Step 1: Setup database**

```powershell
# Ensure all containers running
docker-compose up -d

# Create test table if not exists
docker exec pg-primary psql -U postgres -d testdb -c "
CREATE TABLE IF NOT EXISTS replication_test (
    id SERIAL PRIMARY KEY,
    data TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);"
```

### **Step 2: Create app directory**

```powershell
mkdir app
cd app
```

### **Step 3: Run each pattern**

```powershell
# Pattern 1
python pattern1_primary_routing.py

# Pattern 2
python pattern2_lsn_tracking.py

# Pattern 3
python pattern3_sticky_session.py

# Benchmark
python benchmark_patterns.py
```

---

## 📋 Verification Checklist

After running all patterns:

```
□ Pattern 1: Read-after-write works with primary routing?
□ Pattern 2: LSN comparison prevents stale reads?
□ Pattern 3: Same user always reads from same replica?
□ Benchmark shows latency differences?
□ Understand trade-offs of each approach?
```

---

## 🎓 Key Learnings

### **Pattern Selection Guide:**

| Use Case | Recommended Pattern | Why |
|----------|-------------------|-----|
| Social media posts | Pattern 1 (Time-based) | Simple, 5s is acceptable |
| E-commerce cart | Pattern 2 (LSN-based) | Must see own changes immediately |
| Multi-user chat | Pattern 3 (Sticky) | Prevents message order confusion |
| Analytics dashboard | Read from replicas only | Eventual consistency OK |
| Financial transactions | Read from primary always | Zero tolerance for stale data |

### **Real-world Considerations:**

1. **Connection Pooling**: Reuse connections, don't create per request
2. **Circuit Breaker**: Fallback to primary if replicas down
3. **Observability**: Log which pattern triggered for debugging
4. **A/B Testing**: Measure user experience impact
5. **Graceful Degradation**: Primary-only mode during incidents

---

## 🚀 Next Steps

1. Implement circuit breaker pattern
2. Add connection pooling (PgBouncer)
3. Create monitoring dashboard
4. Test failover scenarios
5. Document runbooks