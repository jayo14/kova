# Runbook: Worker Queue Backup

## 1. Symptom & Alert
- **Alert:** `KovaQueueBackup` (Prometheus)
- **Condition:** `worker_queue_depth > 50` sustained for $\ge 5$ minutes.
- **Impact:** Incoming continuous validation and flow runs are delayed, SLA/SLO breach on PR checks.

## 2. Diagnosis
Run on the production bastion / worker node:

```bash
# 1. Check active Celery tasks across worker queues
celery -A app.workers.celery_app inspect active

# 2. Check registered workers and ping them
celery -A app.workers.celery_app inspect ping

# 3. Check queue backlog in Redis
redis-cli -u $REDIS_URL LLEN kova-enterprise
redis-cli -u $REDIS_URL LLEN kova-pro
redis-cli -u $REDIS_URL LLEN kova-free

# 4. Check Prometheus execution metrics
curl -s http://localhost:8000/metrics | grep -E "executions_started_total|executions_completed_total|worker_queue_depth"
```

Identify whether:
- Tasks are getting stuck (e.g. hung Chromium instances exceeding timeouts).
- Throughput dropped to 0 (worker instances crashed / OOMKilled).
- Sudden spike in traffic (large burst of concurrent PRs from a customer).

## 3. Immediate Mitigation
1. **Scale Celery Workers:**
   - On Render / Fly.io / Kubernetes:
   ```bash
   # Kubernetes example
   kubectl scale deployment kova-worker --replicas=8 -n production

   # Or increase concurrency per worker if host has spare CPU/RAM
   celery -A app.workers.celery_app control autoscale 10,4
   ```
2. **Purge dead / stuck tasks if workers are blocked:**
   ```bash
   # Inspect tasks that have been running for > 15 minutes
   celery -A app.workers.celery_app inspect active_queues
   ```
3. **If queue backlog is unrecoverable and customer approvals granted:**
   ```bash
   # Purge free tier queue to unblock enterprise tier
   celery -A app.workers.celery_app purge -Q kova-free
   ```

## 4. Root-Cause Investigation
- Check worker logs for hung browser sessions:
  `journalctl -u kova-worker -n 200 --no-pager | grep -i "timeout"`
- Check memory usage to verify if workers were OOM-killed:
  `dmesg -T | grep -i oom`
- Inspect slowest targets in database:
  ```sql
  SELECT flow_id, AVG(duration_seconds), count(*) 
  FROM executions 
  WHERE created_at > NOW() - INTERVAL '2 hours' 
  GROUP BY flow_id 
  ORDER BY 2 DESC LIMIT 10;
  ```

## 5. Prevention
- Ensure `TASK_HARD_TIMEOUT = 600` and `soft_time_limit = 540` are strictly enforced.
- Implement autoscaling rules on `worker_queue_depth > 20`.
- Rate-limit continuous validation triggers per project using `OrganizationQuota.max_concurrent_executions`.
