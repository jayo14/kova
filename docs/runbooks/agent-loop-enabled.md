# Runbook: Agent Loop Enabled

## Symptom
The agent loop is now active in production. Executions may behave differently:
- Flows with `objective` but no `steps` now run via `AgentExecutor.run()` instead of the deterministic runner
- Executions may take longer (up to 600s vs the previous 300s cap)
- Executions may end in `BLOCKED` state (destructive action or prompt injection)
- Executions may end in `NEEDS_INPUT` state (agent requests human takeover)

## Diagnosis
- Check execution events for `agent.loop_started`, `agent.loop_turn`, `agent.loop_outcome`
- If `BLOCKED`: check `DESTRUCTIVE_ACTION_BLOCKED` or `INJECTION_ATTEMPT_DETECTED` events
- If `NEEDS_INPUT`: check the LiveViewport — the user must provide input

## Immediate mitigation
- To disable the agent loop entirely: set `AGENT_EXECUTION_ENABLED=false` in the worker env, restart workers
- To reduce the duration cap: set `AGENT_EXECUTION_MAX_DURATION_SECONDS=300` (5 min)

## Root-cause investigation
- If the agent loop is producing too many BLOCKED outcomes, review the project's `safety_restrictions.destructive_action_allowlist` — it may be too restrictive
- If the agent loop is producing too many NEEDS_INPUT outcomes, the agent's `MAX_AGENT_TURNS=60` may be too low for the project's complexity
- If the agent loop is failing on simple flows, check whether AI_PROVIDER is configured and reachable
