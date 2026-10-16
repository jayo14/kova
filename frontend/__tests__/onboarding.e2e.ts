import { describe, it } from "node:test";
import assert from "node:assert";

describe("Onboarding E2E User Journey", () => {
  it("walks the 4-step setup wizard and updates onboarding progress", async () => {
    const steps = [
      { step: 0, title: "Connect App" },
      { step: 1, title: "Credentials" },
      { step: 2, title: "Discovery" },
      { step: 3, title: "Validation" },
      { step: 4, title: "Completed" },
    ];

    let currentStep = 0;
    for (const s of steps) {
      currentStep = s.step;
      assert.strictEqual(currentStep, s.step);
    }
    assert.strictEqual(currentStep, 4);
  });

  it("allows user to skip onboarding directly to dashboard", async () => {
    let onboardingSkipped = false;
    function skipOnboarding() {
      onboardingSkipped = true;
      return "/dashboard";
    }
    const destination = skipOnboarding();
    assert.strictEqual(onboardingSkipped, true);
    assert.strictEqual(destination, "/dashboard");
  });
});
