"""Validated display requests shared by the API and persistence layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class RequestValidationError(ValueError):
    """A client supplied an invalid display request."""


@dataclass(frozen=True)
class DisplayRequest:
    page: str
    title: str | None = None
    body: str | None = None

    @classmethod
    def from_mapping(cls, value: object) -> DisplayRequest:
        """Validate and normalize a JSON-compatible request object."""
        if not isinstance(value, Mapping):
            raise RequestValidationError("request body must be a JSON object")

        unknown = set(value) - {"page", "title", "body"}
        if unknown:
            names = ", ".join(sorted(str(item) for item in unknown))
            raise RequestValidationError(f"unknown field(s): {names}")

        page = value.get("page")
        if not isinstance(page, str):
            raise RequestValidationError("page must be a string")
        page = page.strip().lower()
        if page not in {"standby", "on_air", "message"}:
            raise RequestValidationError(
                "page must be one of: standby, on_air, message"
            )

        if page != "message":
            extra = [name for name in ("title", "body") if name in value]
            if extra:
                raise RequestValidationError(
                    f"{page} does not accept {', '.join(extra)}"
                )
            return cls(page=page)

        title = cls._text(value, "title", maximum=40)
        body = cls._text(value, "body", maximum=240)
        return cls(page=page, title=title, body=body)

    @staticmethod
    def _text(value: Mapping[str, Any], name: str, *, maximum: int) -> str:
        text = value.get(name)
        if not isinstance(text, str) or not text.strip():
            raise RequestValidationError(
                f"{name} is required for the message page"
            )
        result = text.strip()
        if len(result) > maximum:
            raise RequestValidationError(
                f"{name} must be at most {maximum} characters"
            )
        return result

    def to_dict(self) -> dict[str, str]:
        result = {"page": self.page}
        if self.title is not None:
            result["title"] = self.title
        if self.body is not None:
            result["body"] = self.body
        return result
