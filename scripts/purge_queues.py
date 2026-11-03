#!/usr/bin/env python3
"""Safely inspect and purge Celery queues in Redis.

Lists configured queues matching the configured CELERY_QUEUE_PREFIX, prints
their measured lengths (LLEN), and prompts for confirmation before purging.

Usage:
    python scripts/purge_queues.py
    python scripts/purge_queues.py --yes
"""

import argparse
import os
import ssl
import sys
from typing import Any

# Ensure backend directory is in sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import redis  # noqa: E402
from app.config.settings import settings  # noqa: E402


def get_redis_client() -> redis.Redis:
    url = settings.REDIS_URL
    kwargs: dict[str, Any] = {
        "decode_responses": True,
        "socket_connect_timeout": 5.0,
        "socket_timeout": 5.0,
    }
    if "rediss://" in str(url):
        reqs_map = {
            "required": ssl.CERT_REQUIRED,
            "optional": ssl.CERT_OPTIONAL,
            "none": ssl.CERT_NONE,
        }
        kwargs["ssl_cert_reqs"] = reqs_map.get(
            str(settings.REDIS_SSL_CERT_REQS).lower(), ssl.CERT_REQUIRED
        )
        if settings.REDIS_SSL_CA_CERTS:
            kwargs["ssl_ca_certs"] = settings.REDIS_SSL_CA_CERTS
    return redis.from_url(url, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge Celery task queues in Redis.")
    parser.add_argument(
        "-y", "--yes", action="store_true", help="Bypass interactive confirmation."
    )
    args = parser.parse_args()

    r = get_redis_client()
    try:
        r.ping()
    except Exception as exc:
        print(f"Failed to connect to Redis at {settings.REDIS_URL}: {exc}", file=sys.stderr)
        sys.exit(1)

    prefix = settings.CELERY_QUEUE_PREFIX
    target_queues = [
        f"{prefix}kova-free",
        f"{prefix}kova-pro",
        f"{prefix}kova-enterprise",
        f"{prefix}celery",
    ]

    print(f"Checking Redis queues (prefix: '{prefix}')...")
    total_count = 0
    queue_counts = {}

    for q in target_queues:
        try:
            count = r.llen(q)
        except Exception:
            count = 0
        queue_counts[q] = count
        total_count += count
        print(f"  - {q:30s}: {count:5d} messages")

    if total_count == 0:
        print("\nAll queues are already empty. Nothing to purge.")
        return

    print(f"\nTotal messages across queues: {total_count}")

    if not args.yes:
        confirm = input("Are you sure you want to purge all listed queues? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Purge aborted.")
            return

    purged_total = 0
    for q in target_queues:
        count = queue_counts[q]
        if count > 0:
            r.delete(q)
            purged_total += count
            print(f"Purged {q} ({count} messages removed)")

    print(f"\nSuccessfully purged {purged_total} messages across queues.")


if __name__ == "__main__":
    main()
