from __future__ import annotations

from dataclasses import dataclass

from ..errors import UserInterruptedError


@dataclass(slots=True)
class InterruptController:
    interrupted: bool = False
    reason: str = "user"

    def interrupt(self, reason: str = "user") -> None:
        self.interrupted = True
        self.reason = reason

    def raise_if_interrupted(self) -> None:
        if self.interrupted:
            raise UserInterruptedError(f"Interrupted: {self.reason}")
