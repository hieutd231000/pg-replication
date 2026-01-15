# PostgreSQL Streaming Replication

## 📋 Objectives
- Setup 1 Primary + 2 Replicas PostgreSQL
- Test streaming replication
- Simulate replication lag
- Test read-after-write consistency issues

## 🏗️ Architecture

```
┌─────────────┐
│  PRIMARY    │ Port 5432
│  172.21.0.2 │
└──────┬──────┘
       │
       ├──────────┬──────────┐
       │          │          │
┌──────▼─────┐ ┌─▼──────────┐
│ REPLICA 1  │ │ REPLICA 2  │
│ 172.21.0.3 │ │ 172.21.0.4 │
│ Port 5433  │ │ Port 5434  │
└────────────┘ └────────────┘
```

## 🚀 Step 1: Start the Environment

### Clean up old volumes (if needed)
```powershell
cd d:\Project\replication
docker-compose down -v
```

### Start Primary
```powershell
docker-compose up -d pg-primary
```

Wait for primary to start (about 10-15s), check logs:
```powershell
docker logs pg-primary -f
```

Look for: `database system is ready to accept connections`

### Start Replicas
```powershell
docker-compose up -d pg-replica1 pg-replica2
```

Check logs to see the cloning process:
```powershell
docker logs pg-replica1 -f
docker logs pg-replica2 -f
```

## ✅ Step 2: Verify replication status

### Check all running containers
```powershell
docker ps
```

You should see 3 containers: pg-primary, pg-replica1, pg-replica2

### Connect to Primary and check replication
```powershell
docker exec -it pg-primary psql -U postgres -d testdb 

Run verification query:
```sql
SELECT  
    application_name,
    client_addr,
    state,
    sync_state
FROM pg_stat_replication;
```

Expected result: 2 rows (walreceiver from replica1 and replica2)

### pg_stat_replication – Replica States

| State        | Meaning |
|--------------|---------|
| `startup`    | Replica just connected to primary, initializing |
| `catchup`    | Replica is catching up WAL (lagging behind primary) |
| `streaming`  | Replica is receiving WAL in realtime (live sync) ✅ |
| `backup`     | Replica is running `pg_basebackup` |
| `disconnected` | Replica has lost connection / died |


## 🧪 Step 3: Test Replication

### On PRIMARY - Run test script
```powershell
docker exec -it pg-primary psql -U postgres -d testdb -f /docker-entrypoint-initdb.d/test-replication.sql
```

Or copy file in:
```powershell
docker cp test-replication.sql pg-primary:/tmp/
docker exec -it pg-primary psql -U postgres -d testdb -f /tmp/test-replication.sql
```

### On REPLICAS - Verify data
```powershell
# Replica 1
docker exec -it pg-replica1 psql -U postgres -d testdb

# Replica 2
docker exec -it pg-replica2 psql -U postgres -d testdb
```

Run query:
```sql
-- Check role
SELECT pg_is_in_recovery();  -- true = replica

-- Check data
SELECT COUNT(*) FROM replication_test;

-- Check lag
SELECT 
    pg_last_wal_receive_lsn(),
    pg_last_wal_replay_lsn(),
    pg_last_xact_replay_timestamp();
```

### Example: 

#### pg_last_wal_receive_lsn = 0/51B2020
- Replica has received WAL up to position 0/51B2020  
- Like "file downloaded to local machine"

#### pg_last_wal_replay_lsn = 0/51B2020
- Replica has applied (executed) WAL up to position 0/51B2020  
- Like "file extracted and installed"

#### Both LSNs ARE EQUAL → ✅ NO LAG
- Replica has processed all received WAL  
- In perfect "sync" state with master


## 🔥 Step 4: Test Read-After-Write Consistency

### Open 2 terminals
**Terminal 1 - PRIMARY (Write):**
```powershell
docker exec -it pg-primary psql -U postgres -d testdb
```

```sql
-- Insert and note timestamp
INSERT INTO replication_test (data) 
VALUES ('Test-' || NOW()) 
RETURNING id, created_at;
```

**Terminal 2 - REPLICA (Read):**
```powershell
docker exec -it pg-replica2 psql -U postgres -d testdb
```

```sql
-- Immediately query to check if data exists
SELECT * FROM replication_test ORDER BY id DESC LIMIT 5;
```

### Observe lag
If you query immediately, you may not see the data → this is replication lag!

## 📊 Step 5: Simulate and Monitor Replication Lag

### Create bulk write on PRIMARY
```sql
-- Insert 100k rows
INSERT INTO replication_test (data)
SELECT 'Bulk-' || generate_series(1, 100000);
```

### Monitor lag real-time
```sql
SELECT 
    application_name,
    client_addr,
    state,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS lag_size,
    ROUND(EXTRACT(EPOCH FROM replay_lag)::numeric, 2) AS lag_seconds
FROM pg_stat_replication;
```

### Network Throttling Simulation

**Purpose:** Create artificial network latency to observe replication lag more clearly.

#### **Setup network throttling on replica container:**

```powershell
# Add 100ms latency + 10ms jitter to replica1
docker exec -it pg-replica1 bash -c "
apt-get update && apt-get install -y iproute2
tc qdisc add dev eth0 root netem delay 100ms 10ms
"

# Verify throttling
docker exec pg-replica1 tc qdisc show dev eth0
```

#### **Test với throttled network:**

```powershell
# Terminal 1: Monitor replication lag continuously
docker exec pg-primary psql -U postgres -d testdb -c "
SELECT NOW() as time, 
       application_name, 
       ROUND(EXTRACT(EPOCH FROM replay_lag)::numeric, 2) AS lag_sec 
FROM pg_stat_replication;" 
```

```powershell
# Terminal 2: Insert data on primary
docker exec pg-primary psql -U postgres -d testdb -c "
INSERT INTO replication_test (data) 
SELECT 'Throttled-' || generate_series(1, 10000);"
```

**Expected:** replay_lag increases to ~100-200ms instead of 0ms.

#### **Remove throttling:**

```powershell
docker exec pg-replica1 tc qdisc del dev eth0 root
```

#### **Bandwidth limiting (Advanced):**

```powershell
# Limit bandwidth to 1Mbps
docker exec -it pg-replica1 bash -c "
tc qdisc add dev eth0 root tbf rate 1mbit burst 32kbit latency 400ms
"

# Test with large bulk insert
docker exec pg-primary psql -U postgres -d testdb -c "
INSERT INTO replication_test (data) 
SELECT repeat('X', 1000) || generate_series(1, 50000);"

# Monitor bandwidth saturation
docker exec pg-replica1 tc -s qdisc show dev eth0
```

## 🔄 Step 6: Test Monotonic Reads

**Problem:** User reads from replica1 (fresh), then reads from replica2 (lagging) → sees older data = "going back in time"!

### Setup: Create artificial lag on replica2

```powershell
# Stop replica2 temporarily
docker stop pg-replica2
```

### Terminal 1 - Write to PRIMARY:

```powershell
docker exec pg-primary psql -U postgres -d testdb
```

```sql
-- Insert timestamped data
INSERT INTO replication_test (data) 
VALUES ('Monotonic-Test-' || NOW()::TEXT) 
RETURNING id, data, created_at;
-- Note the ID (e.g., 123456)
```

### Terminal 2 - Read from REPLICA1 (up-to-date):

```powershell
docker exec pg-replica1 psql -U postgres -d testdb
```

```sql
-- Should see the new data
SELECT id, data, created_at 
FROM replication_test 
WHERE data LIKE 'Monotonic-Test-%' 
ORDER BY id DESC LIMIT 1;

-- Note: LSN position
SELECT pg_last_wal_replay_lsn();
```

### Start replica2 and read immediately:

```powershell
docker start pg-replica2
# Wait 2-3 seconds (not enough to catch up)
docker exec pg-replica2 psql -U postgres -d testdb
```

```sql
-- Check LSN (should be behind)
SELECT pg_last_wal_replay_lsn();

-- Try to read same data
SELECT id, data, created_at 
FROM replication_test 
WHERE data LIKE 'Monotonic-Test-%' 
ORDER BY id DESC LIMIT 1;

-- May NOT see the data! → Monotonic Reads violated
```

### Observe the problem:

**Scenario:**
1. User reads from Replica1 → sees row ID 123456
2. Load balancer routes next request to Replica2 (lagging)
3. User reads again → doesn't see row 123456
4. User thinks: "Did my data disappear?!" 😱

**Real-world impact:** Shopping cart items disappear, comments vanish, very bad UX!

## 🎯 Important Test Scenarios

### Test 1: Can replica serve reads?
```sql
-- On replica
SELECT COUNT(*) FROM replication_test;  -- OK
INSERT INTO replication_test (data) VALUES ('test');  -- ERROR (read-only)
```

### Test 2: Stop replica, write to primary, start replica again
```powershell
docker stop pg-replica1
```

On primary:
```sql
INSERT INTO replication_test (data) VALUES ('While-replica-down');
```

```powershell
docker start pg-replica1
```

Check if replica automatically catches up.

### Test 3: Network partition simulation
```powershell
# Disconnect replica from network
docker network disconnect pg-replication_pg-replication pg-replica1

# Write to primary
docker exec -it pg-primary psql -U postgres -d testdb -c "INSERT INTO replication_test (data) VALUES ('Partition-test');"

# Reconnect
docker network connect pg-replication_pg-replication pg-replica1 --ip 172.21.0.3

# Verify catch-up
```

## 📈 Monitoring queries

### On PRIMARY - Replication status
```sql
\x
SELECT * FROM pg_stat_replication;
```

### On REPLICA - Lag info
```sql
SELECT 
    NOW() - pg_last_xact_replay_timestamp() AS replication_delay;
```

## 🛠️ Troubleshooting

### Replica cannot connect
```powershell
# Check logs
docker logs pg-replica1

# Check network
docker exec pg-primary ping -c 3 pg-replica1

# Check replication user
docker exec -it pg-primary psql -U postgres -c "\du"
```

### Permission denied error
```powershell
# Rebuild from scratch
docker-compose down -v
docker-compose up -d
```

### Check replication slots
```sql
SELECT * FROM pg_replication_slots;
```

### max_wal_senders exceeded
```
Error: number of requested standby connections exceeds max_wal_senders (currently 3)
```

**Root cause:**
- pg_basebackup needs 1 wal_sender per replica
- Streaming replicas also need wal_senders
- Concurrent starts → race condition

**Solution:**
```conf
# primary/postgresql.conf
max_wal_senders = 5  # 2 replicas + 2 pg_basebackup + 1 buffer
```

**Best practice startup:**
```powershell
docker-compose up -d pg-primary
Start-Sleep -Seconds 20  # Wait for primary stability

# Start replicas sequentially
docker-compose up -d pg-replica1
Start-Sleep -Seconds 10
docker-compose up -d pg-replica2
```

## 🎓 Key Concepts Demonstrated

1. **Streaming Replication**: WAL records are streamed real-time from primary → replicas
2. **Asynchronous Replication**: Primary doesn't wait for replicas to confirm → has lag
3. **Read-After-Write Consistency Issue**: Write to primary, immediate read from replica may not see data
4. **Replication Lag**: Measured in bytes (LSN diff) or time (replay_lag)
5. **Hot Standby**: Replicas can serve read queries

## � Replication Slots - Deep Dive

### **Problem when NOT using Replication Slots:**

Current setup uses `wal_keep_size = 64MB`:
- Primary keeps maximum 64MB WAL segments
- If replica is down, primary continues creating new WAL
- When WAL > 64MB → Primary **DELETES** old WAL
- Replica starts again → **CANNOT catch-up** → Need rebuild!

**Real-world example:**
```powershell
# Insert 10M rows (creates ~400MB WAL)
INSERT INTO replication_test (data) SELECT 'Bulk' || generate_series(1, 10000000);

# Stop replica
docker stop pg-replica1

# Primary has purged WAL > 64MB
# Start replica → ERROR: requested WAL segment has already been removed
docker start pg-replica1  # ❌ FAILED!
```

### **Solution: Replication Slots**

Replication Slots **guarantee** Primary keeps all WAL until replica consumes it.

#### **How it works:**

1. **Slot tracking**: Primary tracks LSN position that each replica has replayed
2. **WAL retention**: Keeps ALL WAL from slot position onwards
3. **Never purge**: Even when `wal_keep_size` exceeded, WAL is not deleted
4. **Replica down 1 week** → Primary still keeps WAL → Replica can catch-up!

#### **Trade-offs:**

**✅ Pros:**
- **Guaranteed catch-up**: Replica can always recover
- **No data loss**: No missed transactions
- **Production ready**: Best practice for production

**⚠️ Cons:**
- **Disk space**: WAL accumulates if replica is down long
- **Monitoring required**: Must monitor disk usage
- **Manual cleanup**: If replica dies permanently, must drop slot manually

### **Setup with Replication Slots:**

#### **Step 1: Create slots in init.sql**

Add to `primary/init.sql`:
```sql
-- Create replication slots for each replica
SELECT pg_create_physical_replication_slot('replica1_slot');
SELECT pg_create_physical_replication_slot('replica2_slot');
```

#### **Step 2: Update pg_basebackup command**

Add flag `-S slot_name`:
```bash
# Replica 1
PGPASSWORD=postgres pg_basebackup -h pg-primary -U replicator \
  -D /var/lib/postgresql/data -Fp -Xs -P -R -S replica1_slot

# Replica 2  
PGPASSWORD=postgres pg_basebackup -h pg-primary -U replicator \
  -D /var/lib/postgresql/data -Fp -Xs -P -R -S replica2_slot
```

#### **Step 3: Verify slots**

```sql
-- On primary
SELECT 
    slot_name,
    slot_type,
    active,
    restart_lsn,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;
```

**Expected output:**
```
 slot_name     | slot_type | active | restart_lsn | retained_wal
---------------+-----------+--------+-------------+--------------
 replica1_slot | physical  | t      | 0/3000060   | 16 MB
 replica2_slot | physical  | t      | 0/3000098   | 16 MB
```

### **Test Scenario: Replica Down with Large Writes**

#### **Test WITHOUT Slots (current):**
```powershell
# 1. Stop replica
docker stop pg-replica1

# 2. Insert 10M rows on primary (creates ~400MB WAL)
docker exec pg-primary psql -U postgres -d testdb -c \
  "INSERT INTO replication_test (data) SELECT 'Bulk' || generate_series(1, 10000000);"

# 3. Start replica
docker start pg-replica1

# 4. Check logs → ❌ FAILED: WAL segment not found
docker logs pg-replica1
```

#### **Test WITH Slots:**
```powershell
# Same steps but with slots enabled

# 1. Stop replica
docker stop pg-replica1

# 2. Insert 10M rows
docker exec pg-primary psql -U postgres -d testdb -c \
  "INSERT INTO replication_test (data) SELECT 'Bulk' || generate_series(1, 10000000);"

# 3. Check retained WAL (should be ~400MB)
docker exec pg-primary psql -U postgres -c \
  "SELECT slot_name, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained 
   FROM pg_replication_slots WHERE slot_name = 'replica1_slot';"

# Output: retained_wal = 400 MB ✅

# 4. Start replica
docker start pg-replica1

# 5. Check logs → ✅ SUCCESS: Catching up from WAL
docker logs pg-replica1 -f

# 6. Verify catch-up
docker exec pg-replica1 psql -U postgres -d testdb -c \
  "SELECT COUNT(*) FROM replication_test;"
```

### **Monitoring Replication Slots:**

```sql
-- Check slot lag
SELECT 
    slot_name,
    active,
    pg_size_pretty(
        pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)
    ) AS lag_size,
    pg_size_pretty(
        pg_wal_lsn_diff(confirmed_flush_lsn, restart_lsn)
    ) AS retained
FROM pg_replication_slots;

-- Alert if lag > 1GB
SELECT slot_name 
FROM pg_replication_slots 
WHERE pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) > 1073741824;
```

### **Cleanup Inactive Slots:**

```sql
-- Drop slot if replica dies permanently
SELECT pg_drop_replication_slot('replica1_slot');

-- Or check and drop inactive slots
DO $$
DECLARE
    slot_rec RECORD;
BEGIN
    FOR slot_rec IN 
        SELECT slot_name FROM pg_replication_slots WHERE NOT active
    LOOP
        PERFORM pg_drop_replication_slot(slot_rec.slot_name);
        RAISE NOTICE 'Dropped slot: %', slot_rec.slot_name;
    END LOOP;
END $$;
```

### **Best Practices:**

1. **Always use slots** in production
2. **Monitor disk usage** with alerting
3. **Set max_slot_wal_keep_size** to limit WAL retention:
   ```conf
   max_slot_wal_keep_size = 10GB  # PostgreSQL 13+
   ```
4. **Automate slot cleanup** for dead replicas
5. **Document slot ownership** (which slot for which replica)

### **Comparison Table:**

| Feature | Without Slots | With Slots |
|---------|--------------|------------|
| WAL retention | wal_keep_size only | Unlimited |
| Replica down recovery | ❌ Limited | ✅ Always possible |
| Disk usage | Bounded | Can grow indefinitely ⚠️ |
| Production ready | ❌ Risky | ✅ Recommended |
| Setup complexity | Simple | Requires slot management |
| Monitoring needs | Low | High (disk usage) |

## �🔗 Connection strings for application

```
Primary (Write):  postgresql://postgres:postgres@localhost:5432/testdb
Replica1 (Read):  postgresql://postgres:postgres@localhost:5433/testdb
Replica2 (Read):  postgresql://postgres:postgres@localhost:5434/testdb
```

## 🧹 Cleanup
```powershell
docker-compose down -v
```
