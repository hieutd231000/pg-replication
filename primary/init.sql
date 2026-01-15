-- Create replication user
CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD 'postgres';

-- Grant necessary permissions
GRANT CONNECT ON DATABASE testdb TO replicator;

-- Create replication slots for each replica (IMPORTANT!)
SELECT pg_create_physical_replication_slot('replica1_slot');
SELECT pg_create_physical_replication_slot('replica2_slot');
