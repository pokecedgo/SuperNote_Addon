"""Microphone recording (16 kHz mono) plus a synthesized demo lecture."""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
MIC_PERMISSION = ("Couldn't use the microphone. Open System Settings → Privacy & Security → "
                  "Microphone and allow your terminal app, then restart SuperNote(Ced++).")


class AudioError(Exception):
    """Message is safe to show to the user."""


class Recorder(ABC):
    """Audio captured since start(), as float32 samples in [-1, 1]."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chunks: List[np.ndarray] = []
        self._joined = np.zeros(0, np.float32)
        self._level = 0.0

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    def _append(self, samples: np.ndarray) -> None:
        with self._lock:
            self._chunks.append(samples.astype(np.float32, copy=False))
            self._level = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0

    def _all(self) -> np.ndarray:
        with self._lock:
            if self._chunks:
                self._joined = np.concatenate([self._joined] + self._chunks)
                self._chunks = []
            return self._joined

    @property
    def seconds(self) -> float:
        return len(self._all()) / SAMPLE_RATE

    @property
    def level(self) -> float:
        return self._level

    def samples(self, start_s: float = 0.0, end_s: Optional[float] = None) -> np.ndarray:
        audio = self._all()
        a = max(0, int(start_s * SAMPLE_RATE))
        b = len(audio) if end_s is None else min(len(audio), int(end_s * SAMPLE_RATE))
        return audio[a:b]

    def save(self, path: Path, start_s: float = 0.0, end_s: Optional[float] = None) -> Path:
        """Write WAV; if `path` ends in .m4a, compress with macOS afconvert (≈1 MB/min)."""
        pcm = (np.clip(self.samples(start_s, end_s), -1, 1) * 32767).astype("<i2")
        wav = path if path.suffix == ".wav" else path.with_suffix(".wav")
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        if path.suffix == ".m4a" and shutil.which("afconvert"):
            try:
                subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "48000",
                                str(wav), str(path)], check=True, capture_output=True, timeout=300)
                wav.unlink()
                return path
            except (subprocess.SubprocessError, OSError) as exc:
                log.warning("afconvert failed (%s); keeping WAV", exc)
        return wav


class MicRecorder(Recorder):
    def __init__(self, device: Optional[int] = None) -> None:
        super().__init__()
        self.device = device
        self._stream = None

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioError("Audio packages aren't installed. Run: "
                             "pip install -r requirements-audio.txt") from exc
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=1600,
                device=self.device, callback=lambda data, *_: self._append(data[:, 0].copy()))
            self._stream.start()
        except Exception as exc:  # PortAudioError and friends
            self._stream = None
            raise AudioError(MIC_PERMISSION) from exc

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None


# --------------------------------------------------------------------- demo lecture
DEMO_LECTURE: List[Tuple[float, str]] = [
    (0.0, "Okay, bueno, let's start. Today we continue with gradients."),
    (7.0, "The gradient is the vector of partial derivatives, and it points in the "
          "direction of steepest ascent."),
    (18.0, "By the way, the midterm moved to next Friday, October tenth, and it covers "
           "chapters twelve through fourteen."),
    (31.0, "Think of it like hiking on a mountain. The gradient tells you which way is "
           "straight uphill."),
    (42.0, "Ojo, this is important for the exam. The gradient is perpendicular to the "
           "level curves."),
    (53.0, "Also, office hours this week are Thursday at three, not Wednesday."),
    (62.0, "Now, the chain rule for a path. dz dt equals f x times x prime plus f y times "
           "y prime."),
]
DEMO_VOICES = ["Diego", "Paulina", "Mónica"]      # Argentine first, if installed


def synthesize_demo_lecture(cache_dir: Path) -> Optional[np.ndarray]:
    """Speak DEMO_LECTURE with macOS `say` onto one timeline. None if unavailable."""
    cache = cache_dir / "demo_lecture.wav"
    if cache.exists():
        with wave.open(str(cache)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32767
    if not (shutil.which("say") and shutil.which("afconvert")):
        return None
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    voice = next((v for v in DEMO_VOICES if v in voices), None)
    total = int((DEMO_LECTURE[-1][0] + 12) * SAMPLE_RATE)
    timeline = np.zeros(total, np.float32)
    with tempfile.TemporaryDirectory() as tmp:
        for i, (t, text) in enumerate(DEMO_LECTURE):
            aiff, wav = Path(tmp) / f"{i}.aiff", Path(tmp) / f"{i}.wav"
            cmd = ["say", "-o", str(aiff)] + (["-v", voice] if voice else []) + [text]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=60)
                subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1",
                                str(aiff), str(wav)], check=True, capture_output=True, timeout=60)
            except (subprocess.SubprocessError, OSError):
                return None
            with wave.open(str(wav)) as w:
                clip = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32767
            a = int(t * SAMPLE_RATE)
            clip = clip[: max(0, total - a)]
            timeline[a:a + len(clip)] += clip
    cache_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(cache), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(timeline, -1, 1) * 32767).astype("<i2").tobytes())
    return timeline


class PlaybackRecorder(Recorder):
    """Feeds pre-made audio in real time, as if it came from the microphone."""

    def __init__(self, audio: np.ndarray) -> None:
        super().__init__()
        self.audio = audio
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        t0, fed = time.monotonic(), 0
        while self._running and fed < len(self.audio):
            due = int((time.monotonic() - t0) * SAMPLE_RATE)
            if due > fed:
                self._append(self.audio[fed:due])
                fed = due
            time.sleep(0.1)
        while self._running:                      # keep "recording" silence afterwards
            time.sleep(0.1)
            self._append(np.zeros(SAMPLE_RATE // 10, np.float32))

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
