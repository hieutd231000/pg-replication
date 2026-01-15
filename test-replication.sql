-- ============================================
-- POSTGRESQL REPLICATION TEST SCRIPT
-- ============================================

-- BƯỚC 1: KIỂM TRA REPLICATION STATUS
-- Chạy trên PRIMARY
\echo '=== 1. CHECK REPLICATION STATUS ON PRIMARY ==='
SELECT 
    application_name,
    client_addr,
    state,
    sync_state,
    pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS send_lag_bytes,
    pg_wal_lsn_diff(pg_current_wal_lsn(), write_lsn) AS write_lag_bytes,
    pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn) AS flush_lag_bytes,
    pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes
FROM pg_stat_replication;

-- BƯỚC 2: TẠO TEST TABLE VÀ INSERT DATA
-- \echo '=== 2. CREATE TEST TABLE AND INSERT DATA ==='
DROP TABLE IF EXISTS replication_test CASCADE;

CREATE TABLE replication_test (
    id SERIAL PRIMARY KEY,
    data TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert initial data
INSERT INTO replication_test (data) 
SELECT 'Test data ' || generate_series(1, 100);

-- Verify data on primary
SELECT COUNT(*) as total_rows FROM replication_test;

-- BƯỚC 3: SIMULATE REPLICATION LAG
\echo '=== 3. SIMULATE REPLICATION LAG (INSERT BULK DATA) ==='
-- Insert large amount of data to create lag
INSERT INTO replication_test (data)
SELECT 'Bulk data ' || generate_series(1, 10000000);

-- Check current LSN
SELECT pg_current_wal_lsn() AS current_lsn;

-- BƯỚC 4: CHECK REPLICATION LAG
\echo '=== 4. CHECK REPLICATION LAG ==='

-- **Các loại lag**:
-- 1. **write_lag**: Thời gian WAL record được gửi từ primary đến khi replica ghi nhận vào WAL buffer (đã nhận qua network).
-- 2. **flush_lag**: Thời gian WAL record được gửi đến khi replica flush WAL xuống disk.
-- 3. **replay_lag**: Thời gian WAL record được gửi đến khi replica apply changes (thực sự có thể query được)

SELECT 
    application_name,
    ROUND(EXTRACT(EPOCH FROM write_lag)::numeric, 2) AS write_lag_sec,
    ROUND(EXTRACT(EPOCH FROM flush_lag)::numeric, 2) AS flush_lag_sec,
    ROUND(EXTRACT(EPOCH FROM replay_lag)::numeric, 2) AS replay_lag_sec,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS replay_lag_size
FROM pg_stat_replication;

-- BƯỚC 5: TEST READ-AFTER-WRITE CONSISTENCY
\echo '=== 5. TEST READ-AFTER-WRITE CONSISTENCY ==='
-- Insert specific data
INSERT INTO replication_test (data) VALUES ('LATEST_WRITE_TEST') RETURNING id, created_at;

-- Ngay lập tức check trên replicas xem đã có data chưa
-- (Chạy query này trên replicas để test)
\echo 'Run this on REPLICAS to check:'
\echo "SELECT * FROM replication_test WHERE data = 'LATEST_WRITE_TEST';"

-- BƯỚC 6: MONITOR REPLICATION SLOTS
\echo '=== 6. CHECK REPLICATION SLOTS ==='
SELECT 
    slot_name,
    slot_type,
    database,
    active,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;

-- BƯỚC 7: CHECK DATABASE SIZE
\echo '=== 7. CHECK DATABASE SIZE ==='
SELECT 
    pg_database.datname,
    pg_size_pretty(pg_database_size(pg_database.datname)) AS size
FROM pg_database
WHERE datname = 'testdb';

-- BƯỚC 8: CONTINUOUS MONITORING QUERY
\echo '=== 8. CONTINUOUS MONITORING (RUN THIS SEPARATELY) ==='
\echo 'Run this in a loop to monitor replication:'
/*
SELECT 
    NOW() AS check_time,
    application_name,
    state,
    pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS lag_size,
    ROUND(EXTRACT(EPOCH FROM replay_lag)::numeric, 2) AS lag_seconds
FROM pg_stat_replication;
*/
