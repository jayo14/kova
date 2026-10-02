import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseKovaInput, normalizeUrl } from "../input-parser";

describe("Kova Input & URL Parser", () => {
  it("parses canonical HTTPS URL without goal", () => {
    const result = parseKovaInput("https://tastiq.app.vercel.app");
    assert.equal(result.url, "https://tastiq.app.vercel.app");
    assert.equal(result.goal, null);
    assert.equal(result.rawInput, "https://tastiq.app.vercel.app");
  });

  it("normalizes domain without protocol to HTTPS", () => {
    const result = parseKovaInput("tastiq.app.vercel.app");
    assert.equal(result.url, "https://tastiq.app.vercel.app");
    assert.equal(result.goal, null);
  });

  it("preserves explicit trailing slash when present in candidate", () => {
    const result = parseKovaInput("https://tastiq.app.vercel.app/");
    assert.equal(result.url, "https://tastiq.app.vercel.app/");
    assert.equal(result.goal, null);
  });

  it("handles short hostnames with protocol like https://tastiq", () => {
    const result = parseKovaInput("https://tastiq");
    assert.equal(result.url, "https://tastiq");
    assert.equal(result.goal, null);
  });

  it("parses URL separated from goal with an em-dash", () => {
    const result = parseKovaInput("https://tastiq.app.vercel.app — test quiz generation");
    assert.equal(result.url, "https://tastiq.app.vercel.app");
    assert.equal(result.goal, "test quiz generation");
    assert.equal(result.rawInput, "https://tastiq.app.vercel.app — test quiz generation");
  });

  it("parses natural language-only query as goal with null URL", () => {
    const result = parseKovaInput("Test whether a student can generate a quiz");
    assert.equal(result.url, null);
    assert.equal(result.goal, "Test whether a student can generate a quiz");
  });

  it("strips enclosing quotes from goals", () => {
    const result = parseKovaInput('https://tastiq.app.vercel.app — "generate a quiz from PDF"');
    assert.equal(result.url, "https://tastiq.app.vercel.app");
    assert.equal(result.goal, "generate a quiz from PDF");
  });

  it("does not split domains containing hyphens", () => {
    const result = parseKovaInput("https://tastiq-app.vercel.app");
    assert.equal(result.url, "https://tastiq-app.vercel.app");
    assert.equal(result.goal, null);
  });

  it("parses domain with spaced hyphen before goal", () => {
    const result = parseKovaInput("https://tastiq-app.vercel.app - test quiz generation");
    assert.equal(result.url, "https://tastiq-app.vercel.app");
    assert.equal(result.goal, "test quiz generation");
  });

  it("parses URL with spaced unquoted goal text without corrupting host", () => {
    const result = parseKovaInput("https://tastiq.app.vercel.app test quiz generation");
    assert.equal(result.url, "https://tastiq.app.vercel.app");
    assert.equal(result.goal, "test quiz generation");
  });

  it("handles localhost with port", () => {
    const result = parseKovaInput("localhost:3000");
    assert.equal(result.url, "http://localhost:3000");
    assert.equal(result.goal, null);
  });

  it("handles localhost with port and goal", () => {
    const result = parseKovaInput("http://localhost:3000 — test login");
    assert.equal(result.url, "http://localhost:3000");
    assert.equal(result.goal, "test login");
  });

  it("handles 127.0.0.1 IP address", () => {
    const result = parseKovaInput("127.0.0.1:8000");
    assert.equal(result.url, "http://127.0.0.1:8000");
    assert.equal(result.goal, null);
  });

  it("preserves path, query parameters, and fragments", () => {
    const result = parseKovaInput("https://example.com/app/quiz?category=math#question-1");
    assert.equal(result.url, "https://example.com/app/quiz?category=math#question-1");
    assert.equal(result.goal, null);
  });

  it("handles empty or whitespace-only input", () => {
    const result = parseKovaInput("   ");
    assert.equal(result.url, null);
    assert.equal(result.goal, null);
    assert.equal(result.rawInput, "");
  });

  it("rejects non-HTTP protocols", () => {
    assert.equal(normalizeUrl("javascript:alert(1)"), null);
    assert.equal(normalizeUrl("file:///etc/passwd"), null);
  });

  it("normalizes hostnames by stripping www and protocol", () => {
    const { normalizeHostname } = require("../input-parser");
    assert.equal(normalizeHostname("https://www.summastudy.com.ng"), "summastudy.com.ng");
    assert.equal(normalizeHostname("www.summastudy.com.ng"), "summastudy.com.ng");
    assert.equal(normalizeHostname("https://summastudy.com.ng/"), "summastudy.com.ng");
    assert.equal(normalizeHostname("http://localhost:3000"), "localhost");
  });

  it("extracts clean project name from www URLs without naming project Www", () => {
    const { extractProjectName } = require("../input-parser");
    assert.equal(extractProjectName("https://www.summastudy.com.ng"), "SummaStudy");
    assert.equal(extractProjectName("www.summastudy.com.ng"), "SummaStudy");
    assert.equal(extractProjectName("https://quotes.toscrape.com"), "Quotes");
    assert.equal(extractProjectName("https://tastiq-app.vercel.app"), "Tastiq App");
    assert.equal(extractProjectName("http://localhost:3000"), "Localhost");
  });
});
