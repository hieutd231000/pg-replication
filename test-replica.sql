-- Check if running on replica
SELECT 
    CASE 
        WHEN pg_is_in_recovery() THEN 'This is a REPLICA (read-only)'
        ELSE 'This is a PRIMARY (read-write)'
    END AS server_role;

-- Check last received WAL location on replica
SELECT 
    pg_last_wal_receive_lsn() AS receive_lsn,
    pg_last_wal_replay_lsn() AS replay_lsn,
    pg_last_xact_replay_timestamp() AS last_replay_time;

-- Check data from test table
SELECT COUNT(*) as total_rows FROM replication_test;

-- Check latest data
SELECT * FROM replication_test ORDER BY id DESC LIMIT 10;

-- Check if specific write has arrived
SELECT * FROM replication_test WHERE data = 'LATEST_WRITE_TEST';
