from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.context import get_current_actor


def log_action(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Record an action in the audit log, attributed to the current actor."""
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=get_current_actor(),
        details=json.dumps(details) if details is not None else None,
    )
    session.add(entry)
    session.flush()
    return entry