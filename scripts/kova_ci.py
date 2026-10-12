#!/usr/bin/env python3
"""Kova Continuous Validation & Regression Testing CLI.

Implements the official Kova CI contract:
Exit Codes:
  0 - Validation completed; all required product flows passed.
  1 - One or more required product flows failed.
  2 - Validation could not produce a trustworthy result (blocked prerequisite, unverified).
  3 - Invalid configuration, authentication failure, or unsupported invocation.
  4 - Kova service, worker, or required infrastructure unavailable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _http_request(
    url: str,
    method: str = "GET",
    token: str | None = None,
    payload: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    """Execute an HTTP request using Python standard library without external dependencies."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data_bytes = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            body = resp.read().decode("utf-8")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = body
            return status_code, parsed
    except urllib.error.HTTPError as err:
        status_code = err.code
        err_body = err.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body)
        except json.JSONDecodeError:
            parsed = {"detail": err_body}
        return status_code, parsed
    except urllib.error.URLError as err:
        raise ConnectionError(f"Cannot connect to Kova API at {url}: {err.reason}") from err


def run_ci(args: argparse.Namespace) -> int:
    api_url = (args.api_url or os.getenv("KOVA_API_URL") or "http://localhost:8000").rstrip("/")
    api_token = args.api_token or os.getenv("KOVA_API_TOKEN")
    project_id = args.project_id or os.getenv("KOVA_PROJECT_ID")

    if not project_id:
        sys.stderr.write("Error: --project-id or KOVA_PROJECT_ID is required.\n")
        return 3

    if not api_token:
        sys.stderr.write("Error: --api-token or KOVA_API_TOKEN is required.\n")
        return 3

    # Parse changed files or diff
    changed_files = []
    if args.changed_files:
        changed_files = [f.strip() for f in args.changed_files.split(",") if f.strip()]

    diff_content = None
    if args.diff_file:
        try:
            with open(args.diff_file, "r", encoding="utf-8") as f:
                diff_content = f.read()
        except OSError as e:
            sys.stderr.write(f"Error reading diff file {args.diff_file}: {e}\n")
            return 3

    payload: dict[str, Any] = {
        "project_id": project_id,
        "commit_sha": args.commit_sha or os.getenv("GITHUB_SHA"),
        "branch": args.branch or os.getenv("GITHUB_REF_NAME"),
        "pr_number": int(args.pr_number) if args.pr_number else None,
        "base_url": args.base_url,
        "scope": args.scope,
        "changed_files": changed_files if changed_files else None,
        "diff_content": diff_content,
        "commit_message": args.commit_message,
        "fail_on_healed": args.fail_on_healed,
    }

    if not args.json_output:
        print("=======================================================")
        print("  Kova Continuous Validation & Regression Testing")
        print("=======================================================")
        print(f"Target API:   {api_url}")
        print(f"Project ID:   {project_id}")
        print(f"Scope:        {args.scope}")
        if payload["commit_sha"]:
            print(f"Commit SHA:   {payload['commit_sha']}")
        if payload["base_url"]:
            print(f"Base URL:     {payload['base_url']}")
        print("Submitting change impact & validation request...")

    # 1. Trigger validation
    validate_url = f"{api_url}/api/v1/ci/validate"
    try:
        status_code, resp = _http_request(validate_url, method="POST", token=api_token, payload=payload)
    except ConnectionError as err:
        sys.stderr.write(f"Infrastructure Error: {err}\n")
        return 4

    if status_code in (401, 403):
        sys.stderr.write(f"Authentication Failure ({status_code}): {resp.get('detail', 'Unauthorized')}\n")
        return 3

    if status_code != 201:
        sys.stderr.write(f"Validation Request Rejected ({status_code}): {resp.get('detail', resp)}\n")
        return 3

    vrun_id = resp.get("id")
    if not vrun_id:
        sys.stderr.write(f"Malformed response from Kova API: missing validation run id\n")
        return 4

    if not args.json_output:
        print(f"Validation Run ID: {vrun_id}")
        impact = resp.get("impact_report", {})
        caps = impact.get("affected_capabilities", [])
        if caps:
            print(f"Affected capabilities detected: {', '.join(caps)}")
        sel_count = len(resp.get("selected_flow_ids", []))
        print(f"Selected product flows: {sel_count}")
        print(f"Waiting for flow executions to complete (timeout: {args.timeout}s)...")

    # 2. Poll until completion or timeout
    start_time = time.time()
    poll_url = f"{api_url}/api/v1/ci/validate/{vrun_id}"
    final_data = None

    while time.time() - start_time < args.timeout:
        time.sleep(args.interval)
        try:
            p_status, p_data = _http_request(poll_url, method="GET", token=api_token)
        except ConnectionError as err:
            sys.stderr.write(f"Connection lost during validation polling: {err}\n")
            return 4

        if p_status != 200:
            sys.stderr.write(f"Polling error ({p_status}): {p_data.get('detail', p_data)}\n")
            return 4

        current_status = p_data.get("status")
        if current_status != "RUNNING":
            final_data = p_data
            break

        if not args.json_output:
            elapsed = int(time.time() - start_time)
            summary = p_data.get("summary", {})
            passed = summary.get("passed", 0)
            failed = summary.get("failed", 0)
            total = summary.get("total_flows", sel_count)
            sys.stdout.write(f"\rProgress [{elapsed}s]: {passed}/{total} passed, {failed} failed...")
            sys.stdout.flush()

    if not final_data:
        sys.stderr.write(f"\nTimeout exceeded ({args.timeout}s): validation did not finish.\n")
        return 2

    # 3. Retrieve detailed report
    report_url = f"{api_url}/api/v1/ci/validate/{vrun_id}/report"
    try:
        r_status, r_data = _http_request(report_url, method="GET", token=api_token)
        if r_status == 200:
            final_data = r_data
    except Exception:
        pass

    exit_code = final_data.get("exit_code")
    if exit_code is None:
        exit_code = 2 if final_data.get("status") in ("BLOCKED", "UNVERIFIED") else 1 if final_data.get("status") == "FAILED" else 0

    if args.json_output:
        print(json.dumps(final_data, indent=2))
        return exit_code

    # 4. Formatted Terminal Output
    print("\n\n=======================================================")
    print(f"  Validation Result: {final_data.get('status')} (Exit Code: {exit_code})")
    print("=======================================================")

    summary = final_data.get("summary", {})
    print(f"Total flows tested: {summary.get('total_flows', 0)}")
    print(f"  - Passed:     {summary.get('passed', 0)}")
    print(f"  - Failed:     {summary.get('failed', 0)}")
    print(f"  - Blocked:    {summary.get('blocked', 0)}")
    print(f"  - Unverified: {summary.get('unverified', 0)}")
    print(f"  - Errors:     {summary.get('error', 0)}")

    diff = final_data.get("baseline_diff", {})
    newly_failing = diff.get("newly_failing", [])
    recovered = diff.get("recovered", [])
    if newly_failing:
        print(f"\n::warning:: NEW REGRESSIONS: {len(newly_failing)} flow(s) newly failed:")
        for fid in newly_failing:
            print(f"  * {fid}")
    if recovered:
        print(f"\n::notice:: RECOVERED: {len(recovered)} flow(s) recovered since baseline.")

    impact = final_data.get("impact_report", {})
    reasons = impact.get("selection_reasons", {})
    if reasons:
        print("\nSelection Rationale:")
        for fid, reason in list(reasons.items())[:5]:
            print(f"  * {fid[:8]}... : {reason}")

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Kova Continuous Validation & Regression Testing CLI")
    parser.add_argument("--project-id", help="Kova project UUID (or KOVA_PROJECT_ID)")
    parser.add_argument("--api-token", help="API authentication token (or KOVA_API_TOKEN)")
    parser.add_argument("--api-url", help="Kova API base URL (default: http://localhost:8000)")
    parser.add_argument("--commit-sha", help="Git commit SHA")
    parser.add_argument("--branch", help="Git branch name")
    parser.add_argument("--pr-number", type=int, help="Pull request number")
    parser.add_argument("--base-url", help="Target deployment or preview URL")
    parser.add_argument(
        "--scope",
        choices=["targeted", "expanded", "full"],
        default="targeted",
        help="Validation scope (default: targeted)",
    )
    parser.add_argument("--changed-files", help="Comma-separated list of changed file paths")
    parser.add_argument("--diff-file", help="Path to unified git diff file")
    parser.add_argument("--commit-message", help="Commit message or PR title")
    parser.add_argument("--timeout", type=int, default=300, help="Max wait time in seconds (default: 300)")
    parser.add_argument("--interval", type=int, default=3, help="Polling interval in seconds (default: 3)")
    parser.add_argument("--fail-on-healed", action="store_true", help="Fail if AI self-healing was used")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON to stdout")

    args = parser.parse_args()
    code = run_ci(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
