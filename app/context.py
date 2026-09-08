from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

DEFAULT_ACTOR = "system"

_current_actor: ContextVar[str] = ContextVar("current_actor", default=DEFAULT_ACTOR)


def get_current_actor() -> str:
    """Return the actor for the current execution context."""
    return _current_actor.get()


def set_current_actor(actor: str) -> None:
    """Set the actor for the current context (process-wide for stdio servers)."""
    _current_actor.set(actor)


@contextmanager
def actor_context(actor: str) -> Iterator[None]:
    """Temporarily set the current actor, restoring the previous value on exit.

    This is what per-request identity will use once the server runs over HTTP.
    """
    token = _current_actor.set(actor)
    try:
        yield
    finally:
        _current_actor.reset(token)