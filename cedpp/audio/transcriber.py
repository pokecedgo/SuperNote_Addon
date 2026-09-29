"""Speech-to-text for lecture audio (local Whisper on Apple Silicon via mlx-whisper)."""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

from .recorder import SAMPLE_RATE, Recorder

log = logging.getLogger(__name__)

# Whisper's initial_prompt is off by default: measured on accented speech it was
# ~3x slower *and* less accurate (it translated "bueno" to "well"). Accent handling
# happens later, in the side-notes prompt to Claude. Set a short vocabulary list
# (e.g. "gradient, Lagrange, Jacobian") in AudioConfig.whisper_prompt if needed.


@dataclass
class Segment:
    start: float        # seconds since recording started
    end: float
    text: str


class Transcript:
    def __init__(self) -> None:
        self.segments: List[Segment] = []
        self._lock = threading.Lock()

    def add(self, segments: List[Segment]) -> None:
        with self._lock:
            self.segments.extend(segments)

    def between(self, start: float, end: float) -> str:
        with self._lock:
            return " ".join(s.text for s in self.segments if s.end > start and s.start < end)

    def tail(self, seconds: float, now: float) -> str:
        return self.between(now - seconds, now + 1)

    def lines(self) -> List[str]:
        with self._lock:
            return [f"[{fmt_time(s.start)}] {s.text}" for s in self.segments]

    @property
    def text(self) -> str:
        with self._lock:
            return " ".join(s.text for s in self.segments)


def fmt_time(seconds: float) -> str:
    s = int(max(0, seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


class Transcriber(ABC):
    name = "transcriber"

    def load(self) -> None:
        """Download/load the model (slow the first time)."""

    @abstractmethod
    def transcribe(self, audio: np.ndarray, offset: float, prompt: str) -> List[Segment]:
        """audio: float32 16 kHz mono starting at `offset` seconds."""


def _looks_hallucinated(text: str) -> bool:
    t = text.strip().lower().strip(".!? ")
    return t in {"", "thank you", "thanks for watching", "you", "bye", "subtitles by"} or \
        (len(t.split()) >= 6 and len(set(t.split())) <= 2)


class WhisperTranscriber(Transcriber):
    name = "whisper"

    def __init__(self, model: str = "mlx-community/whisper-large-v3-turbo",
                 language: Optional[str] = "en", vocabulary: str = "") -> None:
        self.model = model
        self.language = language
        self.vocabulary = vocabulary
        self._path: Optional[str] = None

    def _model_path(self) -> str:
        """Local folder of the model. Uses the cache without touching the network
        (online checks against Hugging Face can take minutes when rate-limited)."""
        if self._path is None:
            from huggingface_hub import snapshot_download
            try:
                self._path = snapshot_download(self.model, local_files_only=True)
            except Exception:
                log.info("Downloading Whisper model %s (first run, ~1.6 GB)…", self.model)
                self._path = snapshot_download(self.model)
        return self._path

    def load(self) -> None:
        """Download if needed and warm the model up (so the first chunk is fast)."""
        import mlx_whisper

        warmup = (np.random.default_rng(0).standard_normal(SAMPLE_RATE) * 0.05).astype(np.float32)
        mlx_whisper.transcribe(warmup, path_or_hf_repo=self._model_path(),
                               language=self.language, verbose=None)

    def transcribe(self, audio: np.ndarray, offset: float, prompt: str) -> List[Segment]:
        import mlx_whisper

        if len(audio) < SAMPLE_RATE // 2 or float(np.sqrt(np.mean(audio ** 2))) < 0.004:
            return []                      # silence: Whisper tends to invent text here
        result = mlx_whisper.transcribe(
            audio.astype(np.float32), path_or_hf_repo=self._model_path(), language=self.language,
            initial_prompt=self.vocabulary or None,
            condition_on_previous_text=False, verbose=None)
        out = []
        for seg in result.get("segments", []):
            text = str(seg.get("text", "")).strip()
            if seg.get("no_speech_prob", 0) > 0.6 or _looks_hallucinated(text):
                continue
            out.append(Segment(offset + float(seg["start"]), offset + float(seg["end"]), text))
        return out


class ScriptTranscriber(Transcriber):
    """For --offline demos: 'hears' the demo lecture script by timestamp."""

    name = "script"

    def __init__(self, script: List[tuple]) -> None:
        self.script = script

    def transcribe(self, audio: np.ndarray, offset: float, prompt: str) -> List[Segment]:
        end = offset + len(audio) / SAMPLE_RATE
        return [Segment(t, t + 6, text) for t, text in self.script if offset <= t < end]


class LiveTranscription:
    """Transcribes the recording in chunks while it grows, cutting at quiet moments."""

    def __init__(self, recorder: Recorder, transcriber: Transcriber, chunk_s: float = 25.0,
                 context_hint: str = "", on_update: Optional[Callable[[], None]] = None) -> None:
        self.recorder = recorder
        self.transcriber = transcriber
        self.chunk_s = chunk_s
        self.context_hint = context_hint
        self.on_update = on_update or (lambda: None)
        self.transcript = Transcript()
        self.error = ""
        self._done_s = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _cut_point(self, end_s: float) -> float:
        """Quietest 0.4 s window in the last 5 s before end_s (so words aren't split)."""
        window = self.recorder.samples(max(self._done_s, end_s - 5), end_s)
        hop = int(0.1 * SAMPLE_RATE)
        size = int(0.4 * SAMPLE_RATE)
        if len(window) < size + hop:
            return end_s
        energies = [float(np.mean(window[i:i + size] ** 2)) for i in range(0, len(window) - size, hop)]
        best = int(np.argmin(energies))
        return end_s - len(window) / SAMPLE_RATE + (best * hop + size / 2) / SAMPLE_RATE

    def _process(self, end_s: float) -> None:
        audio = self.recorder.samples(self._done_s, end_s)
        prompt = (self.context_hint + " " + self.transcript.tail(60, self._done_s)).strip()
        try:
            segments = self.transcriber.transcribe(audio, self._done_s, prompt)
        except Exception as exc:  # keep recording even if transcription breaks
            log.exception("Transcription failed")
            self.error = f"Transcription failed: {exc}"
            segments = []
        self._done_s = end_s
        if segments:
            self.transcript.add(segments)
            self.on_update()

    def _run(self) -> None:
        try:
            self.transcriber.load()
        except Exception as exc:
            log.exception("Couldn't load the transcriber")
            self.error = f"Couldn't load the speech model: {exc}"
        while not self._stop.is_set():
            available = self.recorder.seconds
            if available - self._done_s >= self.chunk_s:
                self._process(self._cut_point(available))
            else:
                self._stop.wait(1.0)

    def finish(self) -> Transcript:
        """Stop, transcribe what's left, return the full transcript (blocking)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        end = self.recorder.seconds
        while end - self._done_s > 0.5:
            self._process(min(end, self._done_s + 30))
        return self.transcript

    def wait_idle(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.recorder.seconds - self._done_s >= self.chunk_s:
            time.sleep(0.1)
