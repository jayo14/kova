from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config.settings import settings
from app.engine.visual.schemas import VisualDefect

logger = logging.getLogger(__name__)


class VLMClient:
    def __init__(self, provider: Any = None, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        self.provider = provider
        self.model = model or getattr(settings, "VLM_MODEL", "gpt-4o-mini")
        self.api_key = api_key or getattr(settings, "VLM_API_KEY", "")
        self.base_url = (base_url or getattr(settings, "VLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")

    def has_vision_capability(self) -> bool:
        """Check if the configured model and client support vision inputs."""
        if not self.api_key:
            return False
        model_lower = (self.model or "").lower()
        non_vision = ["gpt-oss-", "allam-", "text-", "instruct-only", "gpt-3.5"]
        if any(nv in model_lower for nv in non_vision):
            return False
        vision_keywords = ["4o", "vision", "vl", "omni", "gemini", "claude", "pixtral", "image", "llava"]
        return any(vk in model_lower for vk in vision_keywords) or not model_lower.startswith("text-")

    async def escalate_set_of_marks(
        self,
        screenshot_b64: str,
        marks: list[dict[str, Any]],
        objective: str,
        reason: str = "stuck",
        context: str = "",
    ) -> dict[str, Any]:
        """Send a numbered set-of-marks screenshot to a vision-capable model.
        
        Used only when the agent is stuck, a target is ambiguous, or an assertion
        needs visual confirmation. If the model has no vision, skips gracefully and logs.
        """
        if not self.has_vision_capability():
            logger.info("VLMClient: Model '%s' does not have vision capability or no API key is configured. Skipping vision escalation.", self.model)
            return {
                "escalated": False,
                "skipped": True,
                "reason": "no_vision_capability",
                "selected_mark": None,
                "matched_element": None,
            }

        if not screenshot_b64 or not marks:
            logger.info("VLMClient: Missing screenshot or marks. Skipping vision escalation.")
            return {
                "escalated": False,
                "skipped": True,
                "reason": "missing_screenshot_or_marks",
                "selected_mark": None,
                "matched_element": None,
            }

        marks_summary = "\n".join(
            f"[{m['index']}] {m.get('type')}: '{m.get('name')}' (selector: {m.get('selector')})"
            for m in marks[:30]
        )

        prompt_text = (
            f"Objective: {objective}\n"
            f"Escalation Reason: {reason}\n"
            f"Context: {context}\n\n"
            "Interactive elements with numbered marks (red badges on screenshot):\n"
            f"{marks_summary}\n\n"
            "Analyze the screenshot. Find which numbered mark the agent should interact with to achieve the objective, "
            "or verify the visual assertion. Respond ONLY with valid JSON matching:\n"
            "{\n"
            '  "selected_mark": <int mark number or null>,\n'
            '  "action": "<click|fill|press|verify>",\n'
            '  "target_name": "<name of element>",\n'
            '  "reasoning": "<concise explanation>",\n'
            '  "confidence": <float between 0.0 and 1.0>,\n'
            '  "visual_assertion_passed": <true|false|null>\n'
            "}"
        )

        messages = [
            {
                "role": "system",
                "content": "You are an expert QA browser automation visual agent. Respond strictly in valid JSON.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                ],
            },
        ]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                    },
                )
                res.raise_for_status()
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)

                selected_mark = parsed.get("selected_mark")
                matched_element = None
                if isinstance(selected_mark, int):
                    for m in marks:
                        if m.get("index") == selected_mark:
                            matched_element = m
                            break

                return {
                    "escalated": True,
                    "skipped": False,
                    "selected_mark": selected_mark,
                    "action": parsed.get("action", "click"),
                    "target_name": parsed.get("target_name", ""),
                    "reasoning": parsed.get("reasoning", ""),
                    "confidence": float(parsed.get("confidence", 0.8)),
                    "visual_assertion_passed": parsed.get("visual_assertion_passed"),
                    "matched_element": matched_element,
                }
        except Exception as e:
            logger.warning("VLMClient vision escalation failed: %s", e)
            return {
                "escalated": False,
                "skipped": True,
                "reason": f"vlm_error: {e}",
                "selected_mark": None,
                "matched_element": None,
            }

    async def assess_visual_defects(
        self,
        baseline_screenshot_b64: str,
        current_screenshot_b64: str,
        diff_regions: list[dict[str, int]],
        context: str = "",
    ) -> dict[str, Any]:
        """Ask the Vision-Language Model to assess if diff regions represent true visual defects."""
        if not self.api_key:
            logger.info("VLMClient: No API key configured. Skipping VLM assessment.")
            return {
                "assessment": "VLM assessment skipped: no API key configured.",
                "defects": [],
                "confidence": 0.0,
            }

        prompt_text = (
            f"Context: {context}\n"
            f"Diff bounding boxes detected: {diff_regions}\n\n"
            "Assess whether the visual differences between the baseline (first image) and current (second image) "
            "represent actual defects. Classify each defect with type (layout_shift, element_missing, "
            "element_added, color_change, text_overflow, overlap, broken_image, viewport_overflow), "
            "severity (low, medium, high), description, and confidence (0.0 to 1.0).\n"
            "Return JSON matching: {\"assessment\": \"summary text\", \"defects\": [{\"type\": \"...\", \"severity\": \"...\", \"description\": \"...\", \"confidence\": 0.9}]}"
        )

        messages = [
            {
                "role": "system",
                "content": "You are an expert QA visual regression evaluator. Respond in strictly valid JSON.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{baseline_screenshot_b64}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{current_screenshot_b64}"}},
                ],
            },
        ]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                    },
                )
                res.raise_for_status()
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)

                defects = [
                    VisualDefect(
                        type=d.get("type", "layout_shift"),
                        severity=d.get("severity", "medium"),
                        description=d.get("description", "Visual defect detected by VLM"),
                        bounding_box=d.get("bounding_box"),
                        confidence=float(d.get("confidence", 0.8)),
                    )
                    for d in parsed.get("defects", [])
                ]

                return {
                    "assessment": parsed.get("assessment", "VLM assessment completed"),
                    "defects": defects,
                    "confidence": float(parsed.get("confidence", 0.85)),
                }
        except Exception as e:
            logger.warning("VLMClient assessment failed: %s", e)
            return {
                "assessment": f"VLM assessment encountered an error: {e}",
                "defects": [],
                "confidence": 0.0,
            }
