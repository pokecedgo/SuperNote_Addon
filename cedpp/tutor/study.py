"""Study tools for stored pages: 'Summarize Page' and 'Important Takeaways for Exam'."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import List

import numpy as np

from ..config import TutorConfig
from .base import png_bytes
from .claude_tutor import image_block, parse_json_response, request_json

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "description": "What this page is about, 3-8 words."},
        "summary": {"type": "string", "description": "3-5 sentence plain-language summary."},
        "key_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topic", "summary", "key_points"],
    "additionalProperties": False,
}

TAKEAWAYS_SCHEMA = {
    "type": "object",
    "properties": {
        "takeaways": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "point": {"type": "string"},
                    "why": {"type": "string", "description": "Why it matters on an exam."},
                },
                "required": ["point", "why"],
                "additionalProperties": False,
            },
        },
        "practice_questions": {"type": "array", "items": {"type": "string"}},
        "watch_out": {"type": "array", "items": {"type": "string"},
                      "description": "Common mistakes or mistakes seen on this page."},
    },
    "required": ["takeaways", "practice_questions", "watch_out"],
    "additionalProperties": False,
}

NEAT_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "description": "The page's content in reading order.",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["heading", "text", "bullet", "math", "note"]},
                    "text": {"type": "string"},
                },
                "required": ["kind", "text"],
                "additionalProperties": False,
            },
        },
        "unreadable": {"type": "boolean",
                       "description": "True if parts of the page couldn't be read."},
    },
    "required": ["blocks", "unreadable"],
    "additionalProperties": False,
}

BASE_SYSTEM = """\
You help a student study from their own handwritten class notes (an image of \
one notebook page from an e-ink tablet). Read the handwriting carefully, \
including formulas and diagrams. Write math in plain Unicode (∇, ∂, ², ∫, √, →), \
never LaTeX. Only use what's on the page plus standard course knowledge needed to \
explain it; if part of the page is unreadable, say so rather than guessing."""

SUMMARY_TASK = """\
Summarize this page: name the topic, give a 3-5 sentence summary a student could \
reread the night before an exam, and list 3-6 key points (definitions, formulas, \
results) exactly as they'd want them on a review sheet."""

TAKEAWAYS_TASK = """\
Pull out the most important takeaways for an exam: 3-6 points, each with one line \
on why it matters (commonly tested, foundational, easy to lose points on). Add 2-4 \
short practice questions based on this page, and 1-3 'watch out' items for common \
mistakes - including any mistakes actually visible on the page."""


NEAT_TASK = """\
Transcribe this handwritten page into a clean, faithful copy, in reading order. \
Keep the student's own wording, structure and content - fix only obvious spelling \
slips and messy layout, never add new material or correct their math (keep \
mistakes exactly as written). Use block kinds: heading (titles/section names), \
text (sentences), bullet (list items, without the bullet symbol), math (a formula \
or equation on its own line), note (side notes, arrows, boxed reminders). \
Describe a diagram in one short note block like "[diagram: level curves of f]"."""


def transcript_of(blocks: List[dict]) -> str:
    return "\n".join(str(b.get("text", "")).strip() for b in blocks if str(b.get("text", "")).strip())


class StudyAssistant(ABC):
    name = "study"

    @abstractmethod
    def neat_copy(self, page: np.ndarray) -> dict:
        """{'blocks': [{'kind', 'text'}], 'unreadable': bool, 'transcript': str}"""

    @abstractmethod
    def summarize(self, page: np.ndarray, comments: List[dict]) -> dict: ...

    @abstractmethod
    def takeaways(self, page: np.ndarray, comments: List[dict]) -> dict: ...


def _comment_context(comments: List[dict]) -> str:
    lines = []
    for c in comments:
        tip = c.get("tip") or {}
        if tip.get("title"):
            lines.append(f"- {tip['title']}: {tip.get('recognized', '')}")
    return ("Margin comments already made on this page:\n" + "\n".join(lines)) if lines else \
        "No margin comments were made on this page."


class ClaudeStudyAssistant(StudyAssistant):
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

    def _ask(self, page: np.ndarray, comments: List[dict], task: str, schema: dict) -> dict:
        messages = [{"role": "user", "content": [
            image_block(png_bytes(page, max_side=1600)),
            {"type": "text", "text": _comment_context(comments)},
            {"type": "text", "text": task},
        ]}]
        response = request_json(self.client, self.config.model, 8000,
                                self.config.study_effort, BASE_SYSTEM, messages, schema)
        return parse_json_response(response)

    def summarize(self, page: np.ndarray, comments: List[dict]) -> dict:
        return self._ask(page, comments, SUMMARY_TASK, SUMMARY_SCHEMA)

    def neat_copy(self, page: np.ndarray) -> dict:
        messages = [{"role": "user", "content": [
            image_block(png_bytes(page, max_side=1600)),
            {"type": "text", "text": NEAT_TASK},
        ]}]
        response = request_json(self.client, self.config.model, 8000,
                                self.config.study_effort, BASE_SYSTEM, messages, NEAT_SCHEMA)
        data = parse_json_response(response)
        blocks = [{"kind": str(b.get("kind", "text")), "text": str(b.get("text", ""))}
                  for b in data.get("blocks", []) if str(b.get("text", "")).strip()]
        return {"blocks": blocks, "unreadable": bool(data.get("unreadable")),
                "transcript": transcript_of(blocks)}

    def takeaways(self, page: np.ndarray, comments: List[dict]) -> dict:
        return self._ask(page, comments, TAKEAWAYS_TASK, TAKEAWAYS_SCHEMA)


class OfflineStudyAssistant(StudyAssistant):
    """Canned answers for --offline demos (matches the demo notebook page)."""

    name = "offline"

    def __init__(self, delay_s: float = 1.0) -> None:
        self.delay_s = delay_s

    def neat_copy(self, page: np.ndarray) -> dict:
        time.sleep(self.delay_s)
        blocks = [
            {"kind": "heading", "text": "Calc III — Lecture 7"},
            {"kind": "text", "text": "Gradient:"},
            {"kind": "math", "text": "∇f = ⟨ ∂f/∂x , ∂f/∂y ⟩"},
            {"kind": "text", "text": "ex.  f(x, y) = x²y + 3y"},
            {"kind": "math", "text": "∇f = ⟨ 2xy , x² + 2 ⟩"},
            {"kind": "heading", "text": "Chain rule"},
            {"kind": "math", "text": "dz/dt = fₓ · x'(t) + f_y · y'(t)"},
        ]
        return {"blocks": blocks, "unreadable": False, "transcript": transcript_of(blocks)}

    def summarize(self, page: np.ndarray, comments: List[dict]) -> dict:
        time.sleep(self.delay_s)
        return {
            "topic": "Gradients and the multivariable chain rule",
            "summary": ("The gradient ∇f collects a function's partial derivatives into a "
                        "vector that points in the direction of steepest increase. The worked "
                        "example computes ∇f for f(x,y) = x²y + 3y. The page ends with the "
                        "chain rule for a path, dz/dt = fₓ·x'(t) + f_y·y'(t)."),
            "key_points": ["∇f = ⟨∂f/∂x, ∂f/∂y⟩",
                           "For f = x²y + 3y: ∇f = ⟨2xy, x² + 3⟩",
                           "Chain rule along a path: dz/dt = ∇f · r'(t)"],
        }

    def takeaways(self, page: np.ndarray, comments: List[dict]) -> dict:
        time.sleep(self.delay_s)
        return {
            "takeaways": [
                {"point": "∇f points in the direction of steepest ascent",
                 "why": "Shows up in almost every gradient question"},
                {"point": "Directional derivative Dᵤf = ∇f · u",
                 "why": "Common short-answer computation; u must be a unit vector"},
                {"point": "dz/dt = fₓ·x'(t) + f_y·y'(t)",
                 "why": "Chain rule problems are a midterm staple"},
            ],
            "practice_questions": ["Find ∇f for f(x,y) = x²y + 3y at (1, 2).",
                                   "In which direction does f increase fastest at (1, 2)?"],
            "watch_out": ["∂/∂y of (x²y + 3y) is x² + 3 - the page has x² + 2"],
        }


