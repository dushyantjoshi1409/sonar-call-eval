"""Built-in scenario profiles and canonical snapshot hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from voice_eval.domain import ScenarioProfile

_PRESETS: dict[str, dict[str, Any]] = {
    "generic-conversation": {
        "schema_version": "1.0",
        "id": "generic-conversation",
        "name": "Generic conversation",
        "task_description": "Understand the caller and provide a relevant, clear response.",
        "expected_outcome": "The caller's request is understood and a clear next step is stated.",
        "required_information": ["caller intent", "requested next step"],
        "policies": [],
        "custom_criteria": ["Do not invent completed backend actions."],
    },
    "dental-appointment": {
        "schema_version": "1.0",
        "id": "dental-appointment",
        "name": "Dental appointment",
        "task_description": "Help a caller request or manage a dental appointment.",
        "expected_outcome": (
            "Capture the visit reason and timing preference, then state an honest next step."
        ),
        "required_information": ["appointment reason", "preferred date or time"],
        "policies": [],
        "custom_criteria": ["Do not claim a confirmed booking without calendar evidence."],
    },
    "food-delivery": {
        "schema_version": "1.0",
        "id": "food-delivery",
        "name": "Food delivery feedback",
        "task_description": "Collect post-delivery feedback without assuming the order arrived.",
        "expected_outcome": (
            "Establish delivery state, capture relevant feedback, and close appropriately."
        ),
        "required_information": ["delivery state", "relevant feedback"],
        "policies": [],
        "custom_criteria": ["Do not ask for food quality when the order was not delivered."],
    },
}


def get_preset(profile_id: str) -> ScenarioProfile:
    """Return a validated preset or raise ``ValueError`` for an unknown ID."""
    try:
        return ScenarioProfile.model_validate(_PRESETS[profile_id])
    except KeyError as error:
        raise ValueError(f"unknown profile preset: {profile_id}") from error


def list_presets() -> list[ScenarioProfile]:
    """Return fresh validated models for every built-in profile."""
    return [ScenarioProfile.model_validate(item) for item in _PRESETS.values()]


def validate_profile(data: dict[str, Any]) -> ScenarioProfile:
    """Validate untrusted custom profile data against the versioned schema."""
    return ScenarioProfile.model_validate(data)


def profile_hash(profile: ScenarioProfile) -> str:
    """Hash a canonical JSON profile snapshot for immutable run attribution."""
    payload = json.dumps(profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
