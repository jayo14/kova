# Development & Contributing Guide

This guide covers development workflows, code standards, test execution, and pull request guidelines for Kova.

---

## 1. Development Principles

When contributing to Kova, keep the six core engineering invariants in mind:

1. **AI proposes, deterministic code disposes**: Never allow model output directly to trigger raw browser commands or mark runs `COMPLETED`. Model output must be parsed into Pydantic models and validated before execution.
2. **Honest outcomes**: If an action cannot be definitively proven through DOM state, network response, or URL assertions, the state is `UNVERIFIED` or `BLOCKED`—never fake a `PASSED` status.
3. **No product-specific heuristics**: Do not hardcode product-specific selectors, domain rules, or application-specific heuristics. Logic must be universal.
4. **Untrusted page content**: Target pages, emails, and downloads are untrusted inputs. Sanitize prompt inputs, pin DNS to defeat rebinding, and cancel executable downloads.
5. **Ship with tests**: Run the unit and smoke suites before submitting changes.
6. **Keep diffs focused**: Avoid opportunistic refactorings.

---

## 2. Setting Up the Local Development Environment

Follow [docs/local-setup.md](local-setup.md) to set up your Python 3.12+ virtual environment, install backend dependencies, and launch PostgreSQL and Redis.

Verify your environment by running the test suite:
```bash
cd backend
source .venv/bin/activate
pytest tests/unit/ -v
```

---

## 3. Running Test Suites

Kova has a multi-tier test suite covering unit behaviors, provider resilience, integration contracts, and production launch smoke tests:

### Unit Tests
Fast tests that do not require external services or running browser workers:
```bash
cd backend
source .venv/bin/activate
pytest tests/unit/ -v
```

### AI Provider Resilience Tests
Tests verifying tolerant JSON parsing, 404 circuit breaking, and failover routing:
```bash
cd backend
source .venv/bin/activate
pytest tests/unit/test_ai_resilience.py tests/unit/test_ai_providers.py -v
```

### Integration Tests
Tests verifying the browser abstraction layer, DOM observer, and webhook processing:
```bash
cd backend
source .venv/bin/activate
pytest tests/integration/test_observer.py -v
```

### Production Launch Smoke Tests
The reproducible verification suite exercising billing lifecycles, provider degradation, storage resilience, and security invariants:
```bash
./scripts/smoke/run_smoke.sh
```

---

## 4. Code Formatting & Linting

Kova uses `ruff` for linting and code formatting:

```bash
cd backend
source .venv/bin/activate
ruff check .
ruff format --check .
```

To auto-format:
```bash
ruff format .
ruff check --fix .
```

For frontend code:
```bash
cd frontend
npm run lint
```

---

## 5. Pull Request Guidelines

1. **Branch naming**: Use standard prefixes: `feat/`, `fix/`, `docs/`, `test/`.
2. **Commit messages**: Use clear, concise one-line messages explaining the behavior change (e.g., `feat: add tolerant json parser for reasoning models`).
3. **Evidence**: Include test output or screenshots demonstrating the change in action.
