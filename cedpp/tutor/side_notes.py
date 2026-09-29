"""Find what the teacher said *outside* the lecture topic that's worth knowing.

Announcements (exam dates, what's on the exam, deadlines, office hours, events),
plus asides (analogies, stories, study tips). Run once per recording on the
transcript text - no audio or images are sent.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import List

from ..config import TutorConfig
from .claude_tutor import parse_json_response, request_json

ANNOUNCEMENT_KINDS = ["exam", "deadline", "assignment", "event", "logistics"]
ASIDE_KINDS = ["advice", "analogy", "story", "other"]

SIDE_NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "lecture_topic": {"type": "string", "description": "The class topic, 3-8 words."},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ANNOUNCEMENT_KINDS + ASIDE_KINDS},
                    "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                    "summary": {"type": "string",
                                "description": "One clear sentence of what the student needs to know."},
                    "quote": {"type": "string",
                              "description": "Short verbatim excerpt from the transcript."},
                    "start": {"type": "string", "description": "Timestamp [mm:ss] of the quote."},
                    "cue": {"type": "string",
                            "description": "The phrase that signalled it, e.g. 'by the way', 'ojo'."},
                },
                "required": ["kind", "importance", "summary", "quote", "start", "cue"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["lecture_topic", "items"],
    "additionalProperties": False,
}

SYSTEM = """\
You read an automatic transcript of a university lecture and pull out what the \
teacher said OUTSIDE the lecture's subject matter that a student would want to know.

The teacher has an Argentine accent and mixes in Spanish, so the transcript has \
recognition errors: infer what was meant, but keep `quote` close to the transcript \
text and never invent dates, times, rooms or numbers that aren't there.

Listen for the cadence of an aside - phrases like "by the way", "before I forget", \
"just so you know", "quick note", "for the exam", "this will be on the test", \
"remember", "don't forget", "fun fact", "imagine", "think of it like", "it's like", \
"a story", and Spanish cues such as "ojo" (watch out/important), "bueno", "o sea", \
"che", "¿viste?", "digamos", "atención".

Two groups:
1. Announcements (kind exam / deadline / assignment / event / logistics): exam dates \
or content, grading, homework, due dates, office hours, room or schedule changes, \
school events. importance = high if it affects grades, dates or requirements.
2. Asides (kind advice / analogy / story / other): analogies and mental images, \
study tips, "this is important" emphasis, stories, career or life advice.

Do NOT include ordinary explanations of the lecture topic itself. It's fine to \
return an empty list. Keep each summary to one sentence."""


def format_transcript(lines: List[str]) -> str:
    return "\n".join(lines) if lines else "(no speech was transcribed)"


class SideNoteFinder(ABC):
    @abstractmethod
    def find(self, transcript_lines: List[str], notes_context: str = "") -> dict:
        """{'lecture_topic': str, 'items': [...]}, items sorted most important first."""


def _sort(items: List[dict]) -> List[dict]:
    rank = {"high": 0, "medium": 1, "low": 2}
    group = lambda it: 0 if it.get("kind") in ANNOUNCEMENT_KINDS else 1
    return sorted(items, key=lambda it: (group(it), rank.get(it.get("importance"), 3),
                                         it.get("start", "")))


class ClaudeSideNoteFinder(SideNoteFinder):
    def __init__(self, config: TutorConfig = TutorConfig(), client=None) -> None:
        self.config = config
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def find(self, transcript_lines: List[str], notes_context: str = "") -> dict:
        if not transcript_lines:
            return {"lecture_topic": "", "items": []}
        content = [{"type": "text", "text": "Transcript (timestamps are [mm:ss]):\n\n"
                                            + format_transcript(transcript_lines)}]
        if notes_context:
            content.append({"type": "text",
                            "text": "What the student wrote in their notes meanwhile:\n" + notes_context})
        response = request_json(self.client, self.config.model, 8000, self.config.study_effort,
                                SYSTEM, [{"role": "user", "content": content}], SIDE_NOTES_SCHEMA)
        data = parse_json_response(response)
        data["items"] = _sort(list(data.get("items", [])))
        return data


class OfflineSideNoteFinder(SideNoteFinder):
    """Canned result matching the demo lecture (for --offline)."""

    def find(self, transcript_lines: List[str], notes_context: str = "") -> dict:
        time.sleep(1.0)
        items = [
            {"kind": "exam", "importance": "high", "start": "00:18", "cue": "by the way",
             "summary": "The midterm moved to next Friday, October 10, and covers chapters 12–14.",
             "quote": "By the way, the midterm moved to next Friday, October tenth…"},
            {"kind": "logistics", "importance": "medium", "start": "00:53", "cue": "also",
             "summary": "Office hours this week are Thursday at 3, not Wednesday.",
             "quote": "Also, office hours this week are Thursday at three, not Wednesday."},
            {"kind": "advice", "importance": "high", "start": "00:42", "cue": "ojo",
             "summary": "Flagged for the exam: the gradient is perpendicular to level curves.",
             "quote": "Ojo, this is important for the exam…"},
            {"kind": "analogy", "importance": "low", "start": "00:31", "cue": "think of it like",
             "summary": "Gradient = the direction that's straight uphill when hiking a mountain.",
             "quote": "Think of it like hiking on a mountain…"},
        ]
        return {"lecture_topic": "Gradients and the chain rule", "items": _sort(items)}
