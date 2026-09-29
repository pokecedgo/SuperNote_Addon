"""Claude-powered tutor: reads handwriting from the mirror and writes a comment."""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from ..config import TutorConfig
from .base import NoteTutor, Tip, TutorError, TutorRequest, png_bytes

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Ced++, a friendly study buddy who leaves short margin comments on a \
student's handwritten class notes, like a collaborator commenting in a shared doc. \
The student is writing live on an e-ink tablet during a lecture.

You receive two images: (1) a close crop of what the student JUST wrote, and \
(2) the whole page for context, with the new writing boxed in red.

Write one comment about the NEW writing:
- Recognize it (formula, definition, theorem, date, vocab word...) and name it.
- Add a quick insight: what it means, when it's used, or a memory hook.
- In `extras`, give 0-3 short things they could also jot down (related formulas, \
a special case, a common pitfall). Each extra is one line.
- If the new writing contains a likely mistake (wrong sign, wrong exponent, \
arithmetic slip, misspelled key term), set heads_up to true and say plainly and \
kindly what looks off and what it should be.
- Write math in plain Unicode (∇, ∂, ², ⟨ ⟩, ∫, √, →), never LaTeX.
- Be brief: the comment is at most 2 sentences. The student is in class.
- Don't repeat points you already made (listed below as recent comments).

Set skip to true when there's nothing worth a comment: stray marks, scribbles, \
a single letter or number, crossed-out text, page numbers, decorations, or \
tablet interface elements."""

SIGN_IN_MESSAGE = ("Ced++ can't sign in to Claude. Set ANTHROPIC_API_KEY "
                   "(see README) and restart.")

TIP_SCHEMA = {
    "type": "object",
    "properties": {
        "skip": {"type": "boolean"},
        "recognized": {"type": "string",
                       "description": "What the new writing says, transcribed."},
        "title": {"type": "string", "description": "2-5 word name for it."},
        "comment": {"type": "string"},
        "extras": {"type": "array", "items": {"type": "string"}},
        "heads_up": {"type": "boolean"},
    },
    "required": ["skip", "recognized", "title", "comment", "extras", "heads_up"],
    "additionalProperties": False,
}


def _image_block(data: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(data).decode()}}


class ClaudeTutor(NoteTutor):
    name = "claude"

    def __init__(self, config: TutorConfig = TutorConfig(), client=None) -> None:
        self.config = config
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def build_messages(self, request: TutorRequest) -> list:
        history = "\n".join(f"- {h}" for h in request.history) or "(none yet)"
        return [{
            "role": "user",
            "content": [
                {"type": "text", "text": "New writing (close-up):"},
                _image_block(png_bytes(request.crop, max_side=1000)),
                {"type": "text", "text": "Whole page (new writing boxed in red):"},
                _image_block(png_bytes(request.page, max_side=1200, box=request.bbox)),
                {"type": "text", "text": f"Your recent comments on this page:\n{history}"},
            ],
        }]

    def analyze(self, request: TutorRequest) -> Tip:
        import anthropic

        try:
            response = self.client.beta.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=SYSTEM_PROMPT,
                messages=self.build_messages(request),
                output_config={
                    "effort": self.config.effort,
                    "format": {"type": "json_schema", "schema": TIP_SCHEMA},
                },
                # If a safety classifier declines, retry server-side on the
                # recommended fallback model instead of failing the comment.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise TutorError(SIGN_IN_MESSAGE) from exc
        except TypeError as exc:
            # The SDK raises TypeError when no credentials are configured at all.
            if "authentication" in str(exc).lower():
                raise TutorError(SIGN_IN_MESSAGE) from exc
            raise
        except anthropic.PermissionDeniedError as exc:
            raise TutorError("This API key can't use the selected model.") from exc
        except anthropic.RateLimitError as exc:
            raise TutorError("Claude is rate-limiting requests. Try again in a moment.") from exc
        except anthropic.APIStatusError as exc:
            raise TutorError(f"Claude API error ({exc.status_code}). Try again.") from exc
        except anthropic.APIConnectionError as exc:
            raise TutorError("Can't reach Claude. Check your internet connection.") from exc

        return self.parse_response(response)

    @staticmethod
    def parse_response(response) -> Tip:
        if response.stop_reason == "refusal":
            raise TutorError("Ced++ couldn't comment on this one.")
        if response.stop_reason == "max_tokens":
            raise TutorError("The comment came back cut off. Try again.")
        text: Optional[str] = next(
            (b.text for b in response.content if getattr(b, "type", "") == "text"), None)
        if not text:
            raise TutorError("Claude returned an empty comment.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("Unparseable tutor output: %r", text[:200])
            raise TutorError("Couldn't read Claude's reply. Try again.") from exc
        return Tip(
            skip=bool(data.get("skip")),
            recognized=str(data.get("recognized", "")).strip(),
            title=str(data.get("title", "")).strip(),
            comment=str(data.get("comment", "")).strip(),
            extras=[str(e).strip() for e in data.get("extras", []) if str(e).strip()][:3],
            heads_up=bool(data.get("heads_up")),
        )
