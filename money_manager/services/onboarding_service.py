from __future__ import annotations

from typing import Any, Mapping

from money_manager.services.preferences_service import load_preferences, update_preferences
from money_manager.services.profile_service import load_profile


def should_start_onboarding(user_id: str | None = None) -> bool:
    try:
        preferences = load_preferences(user_id=user_id)
    except Exception:
        return False
    # Existing users repaired from older versions should not be trapped: missing
    # values normalize to completed=True. New users are explicitly set to False
    # by user_manager.create_user().
    return bool(preferences.get("onboarding_completed") is False)


def mark_onboarding_completed(user_id: str | None = None) -> dict[str, Any]:
    return update_preferences({"onboarding_completed": True}, user_id=user_id, allow_future_fields=True)


def mark_onboarding_incomplete(user_id: str | None = None) -> dict[str, Any]:
    return update_preferences({"onboarding_completed": False}, user_id=user_id, allow_future_fields=True)


def onboarding_state(user_id: str | None = None) -> dict[str, Any]:
    return {
        "profile": load_profile(user_id=user_id),
        "preferences": load_preferences(user_id=user_id),
        "needs_onboarding": should_start_onboarding(user_id=user_id),
    }
