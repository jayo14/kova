# Runbook: Postgres Connection Exhaustion

## 1. Symptom & Alert
- **Symptom:** API returning HTTP 500 with `OperationalError: remaining connection slots are reserved for non-replication superuser connections` or `too many connections`.
- **Alert:** `KovaHighErrorRate` or RDS / Postgres connection threshold alert (> 85% max_connections).
- **Impact:** Complete API and worker degradation; cannot query projects, create executions, or record states.

## 2. Diagnosis
Connect via superuser / administrative psql session:

```sql
-- 1. Check total current connections vs limit
SELECT count(*), (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_conn
FROM pg_stat_activity;

-- 2. Breakdown connections by state and application
SELECT application_name, state, count(*)
FROM pg_stat_activity
GROUP BY application_name, state
ORDER BY count(*) DESC;

-- 3. Identify long-running transactions and queries
SELECT pid, now() - xact_start AS duration, query, state
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY duration DESC
LIMIT 10;

-- 4. Check for lock contention
SELECT blocked_locks.pid AS blocked_pid,
       blocking_locks.pid AS blocking_pid,
       blocked_activity.query AS blocked_statement,
       blocking_activity.query AS current_statement_in_blocking_process
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

## 3. Immediate Mitigation
1. **Terminate blocking / idle-in-transaction connections:**
   ```sql
   -- Terminate idle-in-transaction connections open for > 5 minutes
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle in transaction'
     AND now() - state_change > interval '5 minutes';

   -- Terminate specific blocking query
   SELECT pg_terminate_backend(<blocking_pid>);
   ```
2. **Restart leaked worker pools if connections were leaked by crashed Celery processes:**
   ```bash
   systemctl restart kova-worker
   ```
3. **If connection pool is undersized for load:**
   Increase connection pool max overflow in PgBouncer or scale connection proxy.

## 4. Root-Cause Investigation
- Check if Celery tasks open database sessions without properly closing or using context managers (`async with async_session_factory() as db:`).
- Check if long-running executions hold open database transactions during Playwright browser automation.
- Verify that `engine.dispose()` is called on server/worker shutdown.

## 5. Prevention
- Enforce strict query statement timeouts in Postgres:
  `ALTER DATABASE kova SET statement_timeout = '15s';`
- Set `idle_in_transaction_session_timeout = '60s'`.
- Deploy PgBouncer in transaction pooling mode between API/workers and Postgres.
- Keep SQLAlchemy pool size capped (`pool_size=20, max_overflow=10`).
