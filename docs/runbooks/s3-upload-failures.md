# Runbook: S3 Upload Failures

## 1. Symptom & Alert
- **Alert:** `KovaS3UploadFailures`
- **Condition:** `rate(evidence_upload_failures_total[5m]) > 0.1` sustained for 5 minutes.
- **Impact:** Video, trace files, DOM snapshots, and step screenshots fail to persist to cloud storage; execution reports lack visual evidence.

## 2. Diagnosis
Execute on bastion or API container:

```bash
# 1. Inspect recent upload failure reasons from Prometheus metrics
curl -s http://localhost:8000/metrics | grep "evidence_upload_failures_total"

# 2. Test S3 connectivity and authentication using aws-cli / boto3 test
python3 -c "
import boto3, os
from app.config.settings import settings
s3 = boto3.client(
    's3',
    endpoint_url=settings.RUMPTYCLOUD_S3_ENDPOINT,
    aws_access_key_id=settings.RUMPTYCLOUD_ACCESS_KEY_ID,
    aws_secret_access_key=settings.RUMPTYCLOUD_SECRET_ACCESS_KEY,
)
print(s3.list_buckets()['Buckets'])
"

# 3. Check bucket quota, lifecycle policies, and credentials expiration
```

Common root causes:
- S3 access key / secret key rotated or expired.
- Bucket permissions / IAM policy changed or revoked.
- Network egress / DNS failure from worker hosts to Rumptycloud S3 endpoint.
- Storage quota exceeded on object store.

## 3. Immediate Mitigation
1. **Fallback to local storage buffering:**
   Ensure workers write artifacts to local fallback directory `/tmp/kova_videos` and `/tmp/kova_evidence` until S3 connectivity is restored.
2. **Update expired credentials:**
   If credentials expired:
   ```bash
   # Update environment variables in secrets manager / production env
   export RUMPTYCLOUD_ACCESS_KEY_ID="<new_key>"
   export RUMPTYCLOUD_SECRET_ACCESS_KEY="<new_secret>"
   systemctl restart kova-worker
   ```
3. **Queue failed uploads for deferred replay:**
   ```bash
   # Review failed artifacts waiting in temp directory
   ls -lh /tmp/kova_videos /tmp/kova_evidence
   ```

## 4. Root-Cause Investigation
- Check application logs for exact HTTP status codes from S3 provider (403 Forbidden vs 500 SlowDown vs 503 Service Unavailable):
  `grep -i "s3" /var/log/kova/worker.log | tail -n 100`
- Check certificate / TLS validity for custom S3 endpoints:
  `openssl s_client -connect s3.rumptycloud.com:443 -servername s3.rumptycloud.com`

## 5. Prevention
- Configure automated alert for credential expiration 14 days before token rotation.
- Set up S3 lifecycle policy to transition older evidence artifacts to cold storage (Glacier/Archive).
- Add retry circuit breaker with exponential backoff on all `boto3` client uploads.
