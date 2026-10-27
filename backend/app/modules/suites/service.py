"""Suite lifecycle, repeatable runs, baselines, flakiness and prioritization."""

from __future__ import annotations

import hashlib
import itertools
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.suites.comparison import (
    assertions_from_events,
    compare_runs,
    failure_signature,
    normalize_assertions,
)
from app.modules.suites.models import SuiteRun, SuiteRunItem, TestSuite
from app.modules.suites.prioritization import prioritize_flows
from app.modules.suites.repository import SuiteRepository
from app.modules.suites.schemas import SuiteCreate, SuiteRunRequest, SuiteUpdate

FlowExecutor = Callable[[dict[str, Any], SuiteRun], Awaitable[dict[str, Any]]]

TERMINAL_RUN_STATUSES = ("completed", "partial")


def _canonical_checksum(snapshot: list[dict[str, Any]]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _flow_snapshot(flow: Any) -> dict[str, Any]:
    return {
        "id": str(flow.id),
        "name": flow.name,
        "description": flow.description,
        "objective": flow.objective,
        "steps": flow.steps or [],
        "success_condition": flow.success_condition,
        "preconditions": flow.preconditions,
        "dependencies": flow.dependencies or [],
        "provides_capabilities": flow.provides_capabilities or [],
        "routes": flow.routes or [],
        "capability": flow.capability,
        "criticality": flow.criticality,
        "mode": flow.mode,
    }


class SuiteService:
    def __init__(self, db: AsyncSession, *, flow_executor: FlowExecutor | None = None):
        self.db = db
        self.repo = SuiteRepository(db)
        self.flow_executor = flow_executor

    async def _load_flows(
        self, project_id: uuid.UUID, flow_ids: list[uuid.UUID]
    ) -> list[Any]:
        from sqlalchemy import select

        from app.modules.flows.models import Flow

        if not flow_ids:
            return []
        result = await self.db.execute(
            select(Flow).where(Flow.id.in_(flow_ids), Flow.project_id == project_id)
        )
        flows = {flow.id: flow for flow in result.scalars().all()}
        missing = [str(flow_id) for flow_id in flow_ids if flow_id not in flows]
        if missing:
            raise ValueError(f"Flows not found in project: {', '.join(missing)}")
        return [flows[flow_id] for flow_id in flow_ids]

    async def create_suite(
        self, data: SuiteCreate, *, user_id: uuid.UUID | None
    ) -> TestSuite:
        existing = await self.repo.list_suites(data.project_id)
        if any(suite.name == data.name for suite in existing):
            raise ValueError(f"Suite '{data.name}' already exists in this project")
        flows = await self._load_flows(data.project_id, data.flow_ids)
        snapshot = [_flow_snapshot(flow) for flow in flows]
        suite = await self.repo.create_suite(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            created_by=user_id,
        )
        await self.repo.create_version(
            suite_id=suite.id,
            version=1,
            flow_snapshot=snapshot,
            checksum=_canonical_checksum(snapshot),
            notes=None,
            created_by=user_id,
        )
        suite.current_version = 1
        await self.db.commit()
        return suite

    async def get_suite(self, suite_id: uuid.UUID) -> TestSuite | None:
        return await self.repo.get_suite(suite_id)

    async def list_suites(self, project_id: uuid.UUID) -> list[TestSuite]:
        return await self.repo.list_suites(project_id)

    async def latest_version(self, suite: TestSuite):
        return await self.repo.get_version(suite.id, suite.current_version)

    async def update_suite(
        self,
        suite: TestSuite,
        data: SuiteUpdate,
        *,
        user_id: uuid.UUID | None,
    ) -> TestSuite:
        if data.name is not None and data.name != suite.name:
            siblings = await self.repo.list_suites(suite.project_id)
            if any(
                sibling.name == data.name and sibling.id != suite.id
                for sibling in siblings
            ):
                raise ValueError(f"Suite '{data.name}' already exists in this project")
            suite.name = data.name
        if data.description is not None:
            suite.description = data.description
        if data.active is not None:
            suite.active = data.active

        if data.flow_ids is not None:
            flows = await self._load_flows(suite.project_id, data.flow_ids)
            snapshot = [_flow_snapshot(flow) for flow in flows]
            checksum = _canonical_checksum(snapshot)
            latest = await self.latest_version(suite)
            if latest is None or latest.checksum != checksum:
                version = (latest.version if latest else 0) + 1
                await self.repo.create_version(
                    suite_id=suite.id,
                    version=version,
                    flow_snapshot=snapshot,
                    checksum=checksum,
                    notes=data.notes,
                    created_by=user_id,
                )
                suite.current_version = version

        await self.db.commit()
        return suite

    async def delete_suite(self, suite: TestSuite) -> None:
        await self.repo.delete_suite(suite)
        await self.db.commit()

    async def suite_detail(self, suite: TestSuite) -> dict[str, Any]:
        version = await self.latest_version(suite)
        runs = await self.repo.list_runs(suite.id, limit=1)
        return {
            "id": suite.id,
            "project_id": suite.project_id,
            "name": suite.name,
            "description": suite.description,
            "active": suite.active,
            "current_version": suite.current_version,
            "created_at": suite.created_at,
            "updated_at": suite.updated_at,
            "version": version,
            "last_run": runs[0] if runs else None,
        }

    async def flakiness(self, suite_id: uuid.UUID) -> dict[str, Any]:
        runs = await self.repo.list_completed_runs(suite_id, limit=5)
        ordered = list(reversed(runs))
        items = await self.repo.list_items_for_runs([run.id for run in ordered])
        by_run: dict[uuid.UUID, list[SuiteRunItem]] = {}
        for item in items:
            by_run.setdefault(item.suite_run_id, []).append(item)
        by_flow: dict[str, dict[str, Any]] = {}
        for run in ordered:
            for item in by_run.get(run.id, []):
                flow_key = str(item.flow_id) if item.flow_id else item.flow_name
                entry = by_flow.setdefault(
                    flow_key,
                    {
                        "flow_id": item.flow_id,
                        "flow_name": item.flow_name,
                        "statuses": [],
                    },
                )
                entry["statuses"].append(item.status)

        flows: list[dict[str, Any]] = []
        for entry in by_flow.values():
            statuses = entry["statuses"][-5:]
            transitions = sum(
                1 for left, right in itertools.pairwise(statuses) if left != right
            )
            has_pass = "passed" in statuses
            has_other = any(status != "passed" for status in statuses)
            flows.append(
                {
                    "flow_id": entry["flow_id"] or uuid.uuid4(),
                    "flow_name": entry["flow_name"],
                    "transitions": transitions,
                    "runs_considered": len(statuses),
                    "statuses": statuses,
                    "flaky": bool(has_pass and has_other and transitions >= 2),
                }
            )
        flows.sort(
            key=lambda entry: (entry["flaky"], entry["transitions"]), reverse=True
        )
        return {"suite_id": suite_id, "flows": flows}

    async def _history(
        self, suite_id: uuid.UUID, exclude_run_id: uuid.UUID | None = None
    ) -> dict[str, dict[str, Any]]:
        runs = await self.repo.list_completed_runs(
            suite_id, limit=5, exclude_run_id=exclude_run_id
        )
        items = await self.repo.list_items_for_runs([run.id for run in runs])
        by_run: dict[uuid.UUID, list[SuiteRunItem]] = {}
        for item in items:
            by_run.setdefault(item.suite_run_id, []).append(item)
        grouped: dict[str, list[str]] = {}
        for run in reversed(runs):
            for item in by_run.get(run.id, []):
                key = str(item.flow_id) if item.flow_id else item.flow_name
                grouped.setdefault(key, []).append(item.status)
        history: dict[str, dict[str, Any]] = {}
        for flow_id, statuses in grouped.items():
            statuses = statuses[-5:]
            transitions = sum(
                1 for left, right in itertools.pairwise(statuses) if left != right
            )
            has_pass = "passed" in statuses
            has_other = any(status != "passed" for status in statuses)
            history[flow_id] = {
                "recent_failure": any(
                    status in ("failed", "error", "blocked", "unverified")
                    for status in statuses
                ),
                "flaky": bool(has_pass and has_other and transitions >= 2),
            }
        return history

    async def _select_baseline(
        self,
        suite: TestSuite,
        version: int,
        requested_id: uuid.UUID | None,
        *,
        exclude_run_id: uuid.UUID | None = None,
    ) -> tuple[SuiteRun | None, str | None]:
        if requested_id is not None:
            baseline = await self.repo.get_run(requested_id)
            if baseline is None or baseline.suite_id != suite.id:
                raise ValueError("Baseline run not found in this suite")
            if baseline.status not in TERMINAL_RUN_STATUSES:
                raise ValueError("Baseline run has not completed")
            return baseline, f"explicit baseline run {baseline.id}"

        same_version = await self.repo.list_completed_runs(
            suite.id, limit=1, exclude_run_id=exclude_run_id, suite_version=version
        )
        if same_version:
            baseline = same_version[0]
            return (
                baseline,
                f"latest completed run of suite version {version} ({baseline.id})",
            )
        any_version = await self.repo.list_completed_runs(
            suite.id, limit=1, exclude_run_id=exclude_run_id
        )
        if any_version:
            baseline = any_version[0]
            return (
                baseline,
                f"latest completed run of older suite version {baseline.suite_version} ({baseline.id})",
            )
        return None, None

    async def _default_executor(
        self, flow: dict[str, Any], run: SuiteRun
    ) -> dict[str, Any]:
        from app.modules.executions.models import ExecutionStatus
        from app.modules.executions.repository import (
            ExecutionEventRepository,
            ExecutionRepository,
        )
        from app.modules.executions.schemas import ExecutionCreate
        from app.modules.executions.service import ExecutionService
        from app.modules.flows.models import Flow
        from app.modules.projects.repository import ProjectRepository

        steps = flow.get("steps") or []
        if not steps:
            return {
                "status": "skipped",
                "duration_ms": 0,
                "assertions": [],
                "failure_signature": None,
                "execution_id": None,
                "error": "Flow has no executable steps",
            }

        flow_model = await self.db.get(Flow, uuid.UUID(flow["id"]))
        if flow_model is None:
            return {
                "status": "error",
                "duration_ms": 0,
                "assertions": [],
                "failure_signature": "flow:missing",
                "execution_id": None,
                "flow_missing": True,
                "error": "Flow no longer exists",
            }

        execution_service = ExecutionService(self.db)
        execution = await execution_service.create_execution(
            ExecutionCreate(flow_id=flow_model.id),
            flow_version=flow_model.version,
            flow_snapshot=flow,
        )
        execution_repo = ExecutionRepository(self.db)
        project = await ProjectRepository(self.db).get_by_id(run.project_id)
        await execution_repo.update_status(execution.id, ExecutionStatus.PLANNING)
        await execution_repo.update_status(execution.id, ExecutionStatus.RUNNING)
        await self.db.commit()

        from app.engine.execution.runner import FlowRunner

        started = time.monotonic()
        try:
            result = await FlowRunner().execute(
                execution_id=execution.id,
                flow_steps=steps,
                success_condition=flow.get("success_condition"),
                preconditions=flow.get("preconditions"),
                target_url=(project.base_url if project else "") or "",
                timeout_seconds=300,
                target_flow=None,
                project=project,
            )
            success = bool(result.get("success"))
            error_code = result.get("error_code")
            if success:
                status = "passed"
            elif error_code == "UNVERIFIED":
                status = "unverified"
            elif error_code == "BLOCKED":
                status = "blocked"
            else:
                status = "failed"
            error_message = result.get("error")
        except Exception as exc:  # noqa: BLE001
            status = "error"
            error_message = str(exc)
            try:
                await execution_repo.update_status(
                    execution.id,
                    ExecutionStatus.ERROR,
                    error_message=error_message[:1000],
                )
                await self.db.commit()
            except Exception:  # noqa: BLE001
                await self.db.rollback()

        events = await ExecutionEventRepository(self.db).list_by_execution(execution.id)
        assertions = assertions_from_events(events)
        return {
            "status": status,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "assertions": assertions,
            "failure_signature": failure_signature(status, assertions),
            "execution_id": execution.id,
            "error": error_message,
        }

    async def run_suite(
        self,
        suite: TestSuite,
        request: SuiteRunRequest,
        *,
        user_id: uuid.UUID | None,
    ) -> SuiteRun:
        if not suite.active:
            raise ValueError("Suite is inactive")

        version = await self.latest_version(suite)
        if version is None:
            raise ValueError("Suite has no versioned flow definition")

        history = await self._history(suite.id)
        selected = prioritize_flows(
            list(version.flow_snapshot or []),
            mode=request.mode,
            changed_files=request.changed_files,
            history=history,
        )

        baseline, baseline_reason = await self._select_baseline(
            suite,
            version.version,
            request.baseline_run_id,
        )

        now = datetime.now(UTC)
        run = await self.repo.create_run(
            suite_id=suite.id,
            project_id=suite.project_id,
            suite_version=version.version,
            suite_snapshot=selected,
            mode=request.mode,
            status="running",
            changed_files=request.changed_files,
            commit_sha=request.commit_sha,
            branch=request.branch,
            summary={},
            created_by=user_id,
            baseline_run_id=baseline.id if baseline else None,
            baseline_reason=baseline_reason,
            started_at=now,
            created_at=now,
        )
        await self.db.commit()

        executor = self.flow_executor or self._default_executor
        current_items: list[dict[str, Any]] = []
        item_rows: list[SuiteRunItem] = []

        for position, flow in enumerate(selected):
            flow_id_raw = flow.get("id")
            flow_uuid = uuid.UUID(flow_id_raw) if flow_id_raw else None
            history_entry = history.get(str(flow_uuid), {}) if flow_uuid else {}
            result: dict[str, Any]
            try:
                result = await executor(flow, run)
            except Exception as exc:  # noqa: BLE001
                result = {
                    "status": "error",
                    "duration_ms": 0,
                    "assertions": [],
                    "failure_signature": f"executor:{type(exc).__name__}",
                    "execution_id": None,
                    "error": str(exc),
                }

            status = str(result.get("status") or "error")
            missing_flow = bool(result.get("flow_missing"))
            item_flow_id = None if missing_flow else flow_uuid
            assertions = normalize_assertions(result.get("assertions"))
            signature = result.get("failure_signature") or failure_signature(
                status, assertions
            )
            item_data = {
                "flow_id": item_flow_id,
                "flow_name": flow.get("name") or str(flow_uuid or "unknown"),
                "position": position,
                "status": status,
                "duration_ms": int(result.get("duration_ms") or 0),
                "assertions": assertions,
                "failure_signature": signature,
                "classification": None,
                "unstable": bool(history_entry.get("flaky")),
                "rationale": "; ".join(flow.get("priority_reasons") or []) or None,
            }
            item = await self.repo.add_item(
                suite_run_id=run.id,
                execution_id=result.get("execution_id"),
                **item_data,
            )
            item_rows.append(item)
            current_items.append(
                {
                    "flow_id": item_flow_id,
                    "flow_name": item_data["flow_name"],
                    "status": status,
                    "assertions": assertions,
                }
            )

        baseline_items: list[dict[str, Any]] | None = None
        if baseline is not None:
            baseline_rows = await self.repo.list_items(baseline.id)
            baseline_items = [
                {
                    "flow_id": row.flow_id,
                    "flow_name": row.flow_name,
                    "status": row.status,
                    "assertions": row.assertions,
                }
                for row in baseline_rows
            ]

        comparison = compare_runs(
            baseline_run_id=str(baseline.id) if baseline else None,
            baseline_reason=baseline_reason,
            baseline_items=baseline_items,
            current_items=current_items,
        )
        classifications = {
            str(item["flow_id"]): item.get("classification")
            for item in current_items
            if item.get("flow_id")
        }
        for row in item_rows:
            row.classification = classifications.get(str(row.flow_id)) or "stable"

        status_counts = {
            "passed": 0,
            "failed": 0,
            "blocked": 0,
            "unverified": 0,
            "skipped": 0,
            "error": 0,
        }
        for item in current_items:
            status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

        planned = len(selected)
        executed = planned - status_counts["skipped"]
        coverage_complete = (
            planned > 0
            and status_counts["skipped"] == 0
            and status_counts["error"] == 0
            and planned == len(selected)
        )
        run_status = (
            "partial"
            if status_counts["skipped"] or status_counts["error"]
            else "completed"
        )
        if planned == 0:
            run_status = "completed"

        counts = comparison["counts"]
        run.summary = {
            "total": planned,
            "executed": executed,
            **status_counts,
            "new_failures": counts["new_failure"],
            "persistent_failures": counts["persistent_failure"],
            "recovered_failures": counts["recovered_failure"],
            "new_coverage": counts["new_coverage"],
            "removed_coverage": counts["removed_coverage"],
            "changed_tests": counts["changed_test"],
            "inconclusive": counts["inconclusive"],
            "flaky": sum(1 for row in item_rows if row.unstable),
            "coverage_complete": coverage_complete,
            "verdict": comparison["verdict"],
            "regressed": counts["new_failure"] > 0,
        }
        run.comparison = comparison
        run.status = run_status
        run.completed_at = datetime.now(UTC)
        await self.db.commit()
        return run

    async def get_run_with_items(self, run: SuiteRun) -> dict[str, Any]:
        items = await self.repo.list_items(run.id)
        return {
            "id": run.id,
            "suite_id": run.suite_id,
            "project_id": run.project_id,
            "suite_version": run.suite_version,
            "mode": run.mode,
            "status": run.status,
            "baseline_run_id": run.baseline_run_id,
            "baseline_reason": run.baseline_reason,
            "comparison": run.comparison,
            "changed_files": run.changed_files,
            "commit_sha": run.commit_sha,
            "branch": run.branch,
            "summary": run.summary,
            "error_message": run.error_message,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "created_at": run.created_at,
            "items": items,
        }
