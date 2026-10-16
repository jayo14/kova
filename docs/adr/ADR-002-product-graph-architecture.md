# ADR-002: Product Graph Architecture as Core IP and Moat

## Status
Accepted

## Date
2026-10-16

## Context
Traditional automated testing tools rely on hardcoded script locators (Cypress, Selenium, Playwright). They suffer from high maintenance overhead, test brittleness on minor UI refactors, and lack holistic awareness of application user journeys.
Conversely, "AI wrapper" agents that blindly prompt LLMs on raw screenshots to decide the next browser click on every step are slow, non-deterministic, astronomically expensive per test run, and unexplainable when tests fail in CI/CD.

We needed a cognitive architecture that:
1. Understands application state transitions, prerequisites, and capabilities deterministically.
2. Self-heals when UI presentation shifts without invalidating semantic invariants.
3. Operates at machine speed without invoking external LLMs for standard test execution.
4. Provides continuous validation on PR diffs with explainable impact reasoning.

## Decision
We adopted the **Product Graph** as Kova's central data structure and foundational intellectual property.
- **Entities**: Pages, Components, Actions, Capabilities, and Invariants are modeled as nodes and directed edges in a persistent topological graph.
- **Deterministic Journey Planning**: Test paths are planned via topological traversals rather than ad-hoc heuristics.
- **Smart Prerequisite Resolution**: Flow prerequisites (such as authentication or state seeding) are resolved automatically by graph traversal before target execution starts.
- **Bounded AI**: Large Language Models are confined to offline flow proposals and ambiguous element disambiguation during discovery, with confidence scores capped at $\le 0.9$. AI is never allowed to determine test pass/fail status or bypass assertion verifiers.
- **Representations**: The graph produces multiple representations on demand: diff-able JSON ASTs, Gherkin feature files, and browser runner instructions.

## Consequences
### Positive
- **Defensible Moat**: The Product Graph creates a compounding data asset for customers. The more their application runs, the richer and more reliable their graph becomes.
- **Execution Speed**: 95% of test executions run with zero LLM API calls, completing in seconds rather than minutes.
- **Reliability & Auditability**: Every step transition is traceable to a specific node, edge, and invariant assertion.
- **Explainable CI Impact**: Code diffs can be projected onto graph nodes to run only affected user flows rather than redundant full-suite executions.

### Negative / Trade-offs
- **Initial Discovery Cost**: Crawling a complex web application to construct the initial graph takes several minutes during first-run onboarding.
- **Schema Complexity**: Maintaining database models and migrations for multi-entity graphs requires rigorous schema governance.
