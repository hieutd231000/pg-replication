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