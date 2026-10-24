"""Parser-facing errors.

Each carries a stable machine ``code`` that the API surfaces and the frontend branches
on, plus a message safe to show a user. Diagnostic detail belongs in the server log,
never in the response.
"""

from __future__ import annotations


class DemoParseError(Exception):
    """A demo could not be turned into a :class:`~app.parsing.model.NormalizedMatch`."""

    code = "parse_failed"
    message = "The demo could not be parsed."

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        super().__init__(message or self.message)
        self.user_message = message or self.message
        self.detail = detail


class InvalidDemoError(DemoParseError):
    """The file is not a demo the parser recognises."""

    code = "invalid_demo"
    message = "The file is not a valid CS2 demo."


class UnsupportedDemoError(DemoParseError):
    """A recognised demo the parser cannot handle (e.g. an incompatible variant)."""

    code = "unsupported_demo"
    message = "This demo variant is not supported."


class EmptyDemoError(DemoParseError):
    """Parsed successfully but contains no rounds — nothing to analyse.

    Distinct from a parse failure on purpose: the UI must tell the two apart.
    """

    code = "empty_demo"
    message = "The demo parsed successfully but contains no completed rounds."
