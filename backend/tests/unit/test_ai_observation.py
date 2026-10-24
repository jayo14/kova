import pytest
from app.engine.ai.observation import (
    rank_interactive_elements,
    compute_observation_diff,
    build_semantic_observation,
)


def test_rank_interactive_elements_prioritizes_buttons_and_required_inputs():
    elements = [
        {"type": "link", "role": "link", "name": "Privacy Policy", "bounding_box": {"x": 10, "y": 900, "width": 100, "height": 20}},
        {
            "type": "input",
            "role": "textbox",
            "name": "email",
            "state": {"required": True, "filled": False},
            "bounding_box": {"x": 100, "y": 200, "width": 200, "height": 30},
        },
        {
            "type": "button",
            "role": "button",
            "name": "Sign In",
            "state": {"disabled": False},
            "bounding_box": {"x": 100, "y": 300, "width": 120, "height": 40},
        },
        {
            "type": "button",
            "role": "button",
            "name": "Disabled Action",
            "state": {"disabled": True},
            "bounding_box": {"x": 100, "y": 400, "width": 120, "height": 40},
        },
    ]

    ranked = rank_interactive_elements(elements)
    names = [e["name"] for e in ranked]

    # Required email input and Sign In button must rank above disabled button and footer link
    assert names.index("Sign In") < names.index("Disabled Action")
    assert names.index("email") < names.index("Privacy Policy")
    assert names[-1] == "Disabled Action"


def test_rank_interactive_elements_boosts_dialog_elements():
    dialogs = [{"bounding_box": {"x": 200, "y": 200, "width": 400, "height": 300}}]
    elements = [
        {
            "type": "button",
            "role": "button",
            "name": "Background Button",
            "bounding_box": {"x": 50, "y": 50, "width": 80, "height": 30},
        },
        {
            "type": "button",
            "role": "button",
            "name": "Dialog Confirm",
            "bounding_box": {"x": 250, "y": 350, "width": 100, "height": 35},
        },
    ]

    ranked = rank_interactive_elements(elements, dialogs=dialogs)
    assert ranked[0]["name"] == "Dialog Confirm"


def test_compute_observation_diff_detects_changes():
    prev = {
        "url": "https://example.com/step1",
        "elements": [
            {"type": "input", "role": "textbox", "name": "username", "frame": "main"},
            {"type": "button", "role": "button", "name": "Next", "frame": "main"},
        ],
        "alerts": [],
    }
    curr = {
        "url": "https://example.com/step2",
        "elements": [
            {"type": "input", "role": "textbox", "name": "otp_code", "frame": "main"},
            {"type": "button", "role": "button", "name": "Verify", "frame": "main"},
        ],
        "alerts": ["Verification code sent to your email."],
    }

    diff = compute_observation_diff(prev, curr)
    assert diff["url_changed"] is True
    assert diff["new_alerts"] == ["Verification code sent to your email."]
    assert any("otp_code" in str(item) or "Verify" in str(item) for item in diff["new_elements"])
    assert any("username" in str(item) or "Next" in str(item) for item in diff["removed_elements"])


def test_build_semantic_observation_structure():
    raw_obs = {
        "url": "https://example.com/login",
        "title": "Login Page",
        "elements": [
            {"type": "input", "role": "textbox", "name": "email", "state": {"required": True, "filled": False}, "bounding_box": {"x": 10, "y": 10, "width": 100, "height": 20}},
            {"type": "button", "role": "button", "name": "Submit", "state": {}, "bounding_box": {"x": 10, "y": 50, "width": 100, "height": 30}},
        ],
        "dialogs": [],
        "alerts": ["Please log in"],
        "iframes": [],
    }

    obs = build_semantic_observation(raw_obs)
    assert obs["url"] == "https://example.com/login"
    assert "ranked_elements" in obs
    assert len(obs["ranked_elements"]) == 2
    assert len(obs["buttons"]) == 1
    assert len(obs["inputs"]) == 1
    assert obs["alerts"] == ["Please log in"]
