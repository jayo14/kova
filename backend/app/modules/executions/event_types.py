"""Event types for execution event system.

Every event is persisted in PostgreSQL as a first-class primitive.
Events form a chronological history for each execution.
"""


class EventTypes:
    """Minimum set of event types for execution lifecycle tracking."""

    # Execution lifecycle
    EXECUTION_CREATED = "execution.created"
    EXECUTION_QUEUED = "execution.queued"
    EXECUTION_INITIALIZING = "execution.initializing"
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_CANCELLED = "execution.cancelled"

    # State-aware execution & Planning lifecycle
    EXECUTION_PLANNED = "execution.planned"
    PREREQUISITE_RESOLVED = "prerequisite.resolved"
    PREREQUISITE_FAILED = "prerequisite.failed"
    STATE_CONTAMINATED = "state.contaminated"
    STATE_RESET = "state.reset"

    # Browser lifecycle
    BROWSER_STARTED = "browser.started"
    BROWSER_CLOSED = "browser.closed"

    # Page lifecycle
    PAGE_LOADED = "page.loaded"

    # Agent observation
    AGENT_OBSERVED = "agent.observed"

    # Action lifecycle
    ACTION_STARTED = "action.started"
    ACTION_COMPLETED = "action.completed"

    # Verification lifecycle
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"

    # Network / Diagnostics
    NETWORK_ERROR = "network.error"

    # Recovery
    RECOVERY_STARTED = "recovery.started"

    # Evidence
    EVIDENCE_CAPTURE_STARTED = "evidence.capture.started"
    EVIDENCE_CAPTURED = "evidence.captured"
    EVIDENCE_FAILED = "evidence.failed"

    # Screenshots
    BROWSER_SCREENSHOT = "browser.screenshot"

    # Takeover / control
    EXECUTION_PAUSED = "execution.paused"
    EXECUTION_HUMAN_CONTROLLED = "execution.human_controlled"
    EXECUTION_RESUMED = "execution.resumed"
    CONTROL_CHANGED = "control.changed"

    # Agent loop (AI layer — proposals and reasoning; never secrets)
    GOAL_INTERPRETED = "agent.goal_interpreted"
    OBSERVATION_CREATED = "agent.observation_created"
    PLAN_CREATED = "agent.plan_created"
    ACTION_PROPOSED = "agent.action_proposed"
    ACTION_VALIDATED = "agent.action_validated"
    STATE_CHANGED = "agent.state_changed"
    REPLAN_TRIGGERED = "agent.replan_triggered"
    RECOVERY_PROPOSED = "agent.recovery_proposed"
    EMAIL_CREATED = "agent.email_created"
    EMAIL_RECEIVED = "agent.email_received"
    EMAIL_LINK_SELECTED = "agent.email_link_selected"
    VERIFICATION_PROPOSED = "agent.verification_proposed"
    VERIFICATION_CONFIRMED = "agent.verification_confirmed"
    HUMAN_INPUT_REQUIRED = "agent.human_input_required"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"

    # AI Proposal & Audit Trail (Hotfix 03 & 07)
    AI_ASSISTED = "agent.ai_assisted"
    AI_PROPOSAL = "agent.ai_proposal"
    AI_PROPOSAL_REJECTED = "agent.ai_proposal_rejected"
    AI_PROPOSAL_ALL_REJECTED = "agent.ai_proposal_all_rejected"

    # Safety Guardrails
    DESTRUCTIVE_ACTION_BLOCKED = "safety.destructive_action_blocked"
    INJECTION_ATTEMPT_DETECTED = "safety.injection_attempt_detected"

    # Agent Loop Production Dispatch
    AGENT_LOOP_STARTED = "agent.loop_started"
    AGENT_LOOP_TURN = "agent.loop_turn"
    AGENT_LOOP_OUTCOME = "agent.loop_outcome"

    # Validation Modes
    DEFECT_DISCOVERED = "defect_discovered"

    # AI Failure Diagnosis & Report Synthesis
    FAILURE_HYPOTHESIS_PROPOSED = "ai.failure_hypothesis_proposed"
    REPORT_SUMMARY_SYNTHESIZED = "ai.report_summary_synthesized"

    # Continuous Validation / Test Maintenance
    FLOW_MARKED_STALE = "flow.marked_stale"
    FLOW_VALIDATED_AGAINST_NEW_GRAPH = "flow.validated_against_new_graph"
    FLOW_REQUIRES_REVIEW = "flow.requires_review"

