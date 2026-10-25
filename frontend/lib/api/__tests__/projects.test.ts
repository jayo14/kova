import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { toFrontendProject, type BackendProject } from "../projects";

describe("Project DTO and Logo Mapping", () => {
  it("maps top-level logo_url when provided by backend", () => {
    const raw: BackendProject = {
      id: "proj-123",
      user_id: "user-456",
      name: "Quiza Ai",
      description: "Automated project for https://quiza-ai.vercel.app",
      base_url: "https://quiza-ai.vercel.app",
      created_at: "2026-10-25T12:00:00Z",
      updated_at: "2026-10-25T12:00:00Z",
      logo_url: "https://quiza-ai.vercel.app/brand-logo.svg",
    };

    const project = toFrontendProject(raw);
    assert.equal(project.id, "proj-123");
    assert.equal(project.name, "Quiza Ai");
    assert.equal(project.logoUrl, "https://quiza-ai.vercel.app/brand-logo.svg");
  });

  it("falls back to env_config.logo_url or favicon_url when top-level logo_url is absent", () => {
    const raw: BackendProject = {
      id: "proj-124",
      user_id: "user-456",
      name: "Quiza Ai",
      description: null,
      base_url: "https://quiza-ai.vercel.app",
      created_at: "2026-10-25T12:00:00Z",
      updated_at: "2026-10-25T12:00:00Z",
      env_config: {
        target: "staging",
        logo_url: "https://quiza-ai.vercel.app/favicon.ico",
      },
    };

    const project = toFrontendProject(raw);
    assert.equal(project.logoUrl, "https://quiza-ai.vercel.app/favicon.ico");
  });

  it("defaults to null when no logo is in the raw project", () => {
    const raw: BackendProject = {
      id: "proj-125",
      user_id: "user-456",
      name: "New Product",
      description: null,
      base_url: "https://example.com",
      created_at: "2026-10-25T12:00:00Z",
      updated_at: "2026-10-25T12:00:00Z",
      env_config: {
        target: "development",
      },
    };

    const project = toFrontendProject(raw);
    assert.equal(project.logoUrl, null);
  });
});
