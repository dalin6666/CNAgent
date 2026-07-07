from __future__ import annotations

"""Helpers for auto-generated placeholder mirror modules."""

from typing import Any


def _message(name: str, source_path: str) -> str:
    return f"{name} is a placeholder mirror for {source_path} and has not been fully ported yet."


def placeholder_function(name: str, source_path: str):
    def _placeholder(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(_message(name, source_path))

    _placeholder.__name__ = name
    _placeholder.__doc__ = _message(name, source_path)
    return _placeholder


def placeholder_class(name: str, source_path: str):
    class _Placeholder:
        __doc__ = _message(name, source_path)

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        def __repr__(self) -> str:
            return f"<{name} placeholder from {source_path}>"

    _Placeholder.__name__ = name
    return _Placeholder
