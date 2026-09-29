"""Lecture audio: chunked transcription, transcript context, side-notes digest."""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cedpp.audio import (SAMPLE_RATE, LiveTranscription, Recorder, ScriptTranscriber, Segment,
                         Transcriber, fmt_time)
from cedpp.tutor.side_notes import ClaudeSideNoteFinder, _sort
from cedpp.ui.lecture_audio import digest_markdown


class FakeRecorder(Recorder):
    def __init__(self, audio):
        super().__init__()
        self._append(audio)

    def start(self):
        pass

    def stop(self):
        pass


def speech_with_pause(total_s=40, pause_at=23.0):
    rng = np.random.default_rng(0)
    audio = (rng.standard_normal(total_s * SAMPLE_RATE) * 0.2).astype(np.float32)
    a = int(pause_at * SAMPLE_RATE)
    audio[a:a + int(0.6 * SAMPLE_RATE)] = 0.0          # a breath between sentences
    return audio


class RecordingTranscriber(Transcriber):
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, offset, prompt):
        self.calls.append((offset, len(audio) / SAMPLE_RATE, prompt))
        return [Segment(offset, offset + len(audio) / SAMPLE_RATE, f"chunk@{offset:.1f}")]


def test_chunks_are_cut_at_the_quiet_moment_and_everything_gets_transcribed():
    rec = FakeRecorder(speech_with_pause(40, pause_at=23.0))
    tr = RecordingTranscriber()
    live = LiveTranscription(rec, tr, chunk_s=25.0, context_hint="Calc III")
    cut = live._cut_point(25.0)
    assert 23.0 <= cut <= 23.7
    transcript = live.finish()
    covered = sum(length for _, length, _ in tr.calls)
    assert abs(covered - 40) < 0.6                     # nothing lost
    assert "Calc III" in tr.calls[-1][2]               # context hint in the prompt
    assert transcript.lines()[0].startswith("[00:00]")


def test_transcript_tail_gives_recent_speech_for_comments():
    script = [(0, "intro"), (30, "gradient points uphill"), (100, "chain rule")]
    rec = FakeRecorder(np.zeros(110 * SAMPLE_RATE, np.float32))
    live = LiveTranscription(rec, ScriptTranscriber(script), chunk_s=25)
    t = live.finish()
    assert "gradient" in t.tail(90, 60) and "chain rule" not in t.tail(90, 60)
    assert fmt_time(3725) == "1:02:05" and fmt_time(83) == "01:23"


def test_side_notes_prompt_and_sorting():
    sent = {}
    items = [
        {"kind": "analogy", "importance": "low", "summary": "hiking", "quote": "q",
         "start": "00:31", "cue": "like"},
        {"kind": "exam", "importance": "high", "summary": "midterm Friday", "quote": "q",
         "start": "00:18", "cue": "by the way"},
        {"kind": "logistics", "importance": "medium", "summary": "office hours", "quote": "q",
         "start": "00:53", "cue": "also"},
    ]

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
                type="text", text=json.dumps({"lecture_topic": "Gradients", "items": items}))])

    finder = ClaudeSideNoteFinder(client=SimpleNamespace(beta=SimpleNamespace(messages=Messages())))
    out = finder.find(["[00:18] By the way, the midterm moved to Friday."], "Gradient: ∇f")
    assert [i["kind"] for i in out["items"]] == ["exam", "logistics", "analogy"]
    assert "Argentine" in sent["system"] and "ojo" in sent["system"]
    texts = [b["text"] for b in sent["messages"][0]["content"]]
    assert "[00:18] By the way" in texts[0] and "∇f" in texts[1]
    assert finder.find([]) == {"lecture_topic": "", "items": []}      # no call on silence
    md = digest_markdown(out, "lecture.m4a")
    assert "EXAM" in md and "midterm Friday" in md


def test_sort_puts_announcements_before_asides():
    items = [{"kind": "advice", "importance": "high", "start": "01:00"},
             {"kind": "event", "importance": "low", "start": "02:00"}]
    assert _sort(items)[0]["kind"] == "event"


def test_recorder_saves_a_window_as_wav(tmp_path):
    rec = FakeRecorder(np.linspace(-0.5, 0.5, 10 * SAMPLE_RATE).astype(np.float32))
    path = rec.save(tmp_path / "clip.wav", 2.0, 5.0)
    with wave.open(str(path)) as w:
        assert w.getframerate() == SAMPLE_RATE and w.getnframes() == 3 * SAMPLE_RATE
