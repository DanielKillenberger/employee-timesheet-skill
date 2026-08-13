"""Structured error type shared by every timesheet subcommand.

Errors always surface as JSON ``{code, message, detail}`` and a non-zero exit,
so Claude can relay ``message`` verbatim to the user (plan decision 8).
"""

from __future__ import annotations

from typing import Any


class TimesheetError(Exception):
    """A user-facing, plain-language failure with a stable machine code."""

    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}
