"""App-level settings: DB-backed preferences behind the dashboard's gear icon.

Configuration is deliberately two-tier. Infrastructure — credentials, ports,
LLM keys, schedule intervals — lives in ``.env`` and needs a restart to
change. The knobs here are behavioral: they're read per request, safe to
change at runtime, and every key has a code-owned default, so the table only
stores what the user overrode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from .database import engine
from .models import Setting


@dataclass(frozen=True)
class Spec:
    default: Any
    kind: type
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] | None = None


SPECS: dict[str, Spec] = {
    # Meal Ideas card defaults (the card still lets you change them ad hoc)
    "meals.profile": Spec(default="family", kind=str),
    "meals.count": Spec(default=3, kind=int, lo=1, hi=6),
    "meals.context": Spec(default="trip", kind=str, choices=("trip", "days")),
    "meals.days": Spec(default=14, kind=int, lo=3, hi=60),
    # Restock radar
    "restock.horizon_days": Spec(default=3, kind=int, lo=1, hi=14),
    "restock.min_purchases": Spec(default=3, kind=int, lo=2, hi=10),
    # Budget forecast
    "budget.history_months": Spec(default=6, kind=int, lo=2, hi=24),
    "budget.anomaly_factor": Spec(default=1.5, kind=float, lo=1.1, hi=5.0),
}


def get_settings() -> dict[str, Any]:
    """Code defaults overlaid with whatever the user saved."""
    merged: dict[str, Any] = {key: spec.default for key, spec in SPECS.items()}
    with Session(engine) as session:
        for row in session.exec(select(Setting)).all():
            if row.key in SPECS:
                try:
                    merged[row.key] = json.loads(row.value)
                except ValueError:
                    pass  # corrupt row — fall back to the default
    return merged


def _validated(key: str, value: Any) -> Any:
    spec = SPECS.get(key)
    if spec is None:
        raise ValueError(f"Unknown setting {key!r}.")
    if spec.kind is int:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
            raise ValueError(f"{key} must be a whole number.")
        value = int(value)
    elif spec.kind is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number.")
        value = float(value)
    else:
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise ValueError(f"{key} must be a short text value.")
        value = value.strip()
    if spec.lo is not None and value < spec.lo:
        raise ValueError(f"{key} must be at least {spec.lo}.")
    if spec.hi is not None and value > spec.hi:
        raise ValueError(f"{key} must be at most {spec.hi}.")
    if spec.choices and value not in spec.choices:
        raise ValueError(f"{key} must be one of: {', '.join(spec.choices)}.")
    return value


def update_settings(values: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist overrides; returns the full merged settings."""
    cleaned = {key: _validated(key, value) for key, value in values.items()}
    with Session(engine) as session:
        for key, value in cleaned.items():
            row = session.get(Setting, key)
            if row is None:
                session.add(Setting(key=key, value=json.dumps(value)))
            else:
                row.value = json.dumps(value)
        session.commit()
    return get_settings()
