from __future__ import annotations

from agent_runtime.schemas import SessionState

from .types import ContextSessionState

_CONTEXT_STATE_KEY = "_context_state"


def load_context_state(session: SessionState) -> ContextSessionState:
    raw = session.context_state or session.metadata.get(_CONTEXT_STATE_KEY)
    state = ContextSessionState.from_dict(raw if isinstance(raw, dict) else None)
    session.context_state = state.to_dict()
    session.metadata[_CONTEXT_STATE_KEY] = session.context_state
    return state


def save_context_state(session: SessionState, state: ContextSessionState) -> None:
    payload = state.to_dict()
    session.context_state = payload
    session.metadata[_CONTEXT_STATE_KEY] = payload
