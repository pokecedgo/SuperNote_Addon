"""Lecture audio for a recording session: mic → live transcript → side-notes digest."""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from ..audio import LiveTranscription, Recorder, Transcriber, fmt_time
from ..config import AudioConfig
from ..tutor import TutorError
from ..tutor.side_notes import SideNoteFinder
from .workers import TaskThread

log = logging.getLogger(__name__)


class LectureAudio(QObject):
    transcript_updated = Signal(int)          # number of transcribed lines
    digest_ready = Signal(object, object)     # result dict (or None), session folder
    digest_failed = Signal(str)

    def __init__(self, config: AudioConfig, make_recorder: Callable[[], Recorder],
                 make_transcriber: Callable[[], Optional[Transcriber]],
                 finder: SideNoteFinder) -> None:
        super().__init__()
        self.cfg = config
        self.make_recorder = make_recorder
        self.make_transcriber = make_transcriber
        self.finder = finder
        self.recorder: Optional[Recorder] = None
        self.live: Optional[LiveTranscription] = None
        self.note = ""                          # e.g. "no transcripts: install audio extras"
        self.saved_audio: Optional[Path] = None  # set once the session's audio is saved
        self._recording = False
        self._thread: Optional[TaskThread] = None

    # ------------------------------------------------------------------ session
    @property
    def active(self) -> bool:
        """True while the microphone is recording."""
        return self._recording

    def start(self, context_hint: str = "") -> None:
        """Raises AudioError (message for the user) if the mic can't be used."""
        recorder = self.make_recorder()
        recorder.start()
        self.recorder = recorder
        self.saved_audio = None
        self._recording = True
        transcriber = self.make_transcriber()
        self.note = "" if transcriber else ("recording audio only - install "
                                            "requirements-audio.txt for transcripts")
        if transcriber is not None:
            self.live = LiveTranscription(
                recorder, transcriber, self.cfg.chunk_s, context_hint,
                on_update=lambda: self.transcript_updated.emit(len(self.live.transcript.segments)))
            self.live.start()

    def now(self) -> Optional[float]:
        return self.recorder.seconds if self.recorder and self._recording else None

    def context(self, at: Optional[float]) -> str:
        """What the teacher said in the seconds before `at` (for comments)."""
        if self.live is None or at is None:
            return ""
        return self.live.transcript.tail(self.cfg.context_s, at)

    def stop(self, folder: Path, notes_context: str) -> None:
        """Stop recording; finish the transcript, save everything and find side notes
        in the background. Emits digest_ready(result, folder) when done."""
        recorder, live = self.recorder, self.live
        if recorder is None or not self._recording:
            return
        self._recording = False
        recorder.stop()

        def work():
            folder.mkdir(parents=True, exist_ok=True)
            audio_path = recorder.save(folder / "lecture.m4a")
            lines: List[str] = []
            if live is not None:
                transcript = live.finish()
                lines = transcript.lines()
                (folder / "transcript.txt").write_text("\n".join(lines) + "\n")
            result = None
            error = ""
            if lines:
                try:
                    result = self.finder.find(lines, notes_context)
                except TutorError as exc:
                    error = str(exc)
                if result is not None:
                    (folder / "side_notes.json").write_text(
                        json.dumps(result, indent=2, ensure_ascii=False))
                    (folder / "lecture.md").write_text(digest_markdown(result, audio_path.name))
            return result, error, audio_path

        self._thread = TaskThread(work)
        self._thread.succeeded.connect(lambda res: self._stopped(res, folder))
        self._thread.start()

    def _stopped(self, res, folder: Path) -> None:
        if res is None:
            self.digest_failed.emit("Couldn't finish the lecture recording.")
            return
        result, error, audio_path = res
        self.saved_audio = audio_path
        if error:
            self.digest_failed.emit(error)
        self.digest_ready.emit(result, folder)

    def wait(self) -> None:
        if self._thread is not None:
            self._thread.wait(120000)


def digest_markdown(result: dict, audio_name: str) -> str:
    lines = [f"# Lecture side notes · {result.get('lecture_topic', '')}", "",
             f"Audio: `{audio_name}`", ""]
    for item in result.get("items", []):
        lines.append(f"- **[{item.get('start', '')}] {item.get('kind', '').upper()}** "
                     f"({item.get('importance', '')}): {item.get('summary', '')}  ")
        lines.append(f"  > {item.get('quote', '')}")
    if not result.get("items"):
        lines.append("Nothing outside the lecture topic was mentioned.")
    return "\n".join(lines) + "\n"


class ClipPlayer(QObject):
    """Plays a short window of the lecture recording (e.g. from a comment's ▶)."""

    def __init__(self) -> None:
        super().__init__()
        self.player = QMediaPlayer()
        self.output = QAudioOutput()
        self.player.setAudioOutput(self.output)
        self._tmp = Path(tempfile.gettempdir()) / "supernote_cedpp_clip.wav"

    def play(self, recorder: Recorder, start_s: float, length_s: float = 60.0) -> str:
        start_s = max(0.0, start_s)
        self.player.stop()
        self.player.setSource(QUrl())
        recorder.save(self._tmp, start_s, start_s + length_s)
        self.player.setSource(QUrl.fromLocalFile(str(self._tmp)))
        self.player.play()
        return f"Playing the lecture from {fmt_time(start_s)}…"

    def play_file(self, path: Path, start_s: float) -> str:
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.setPosition(int(max(0.0, start_s) * 1000))
        self.player.play()
        return f"Playing the lecture from {fmt_time(start_s)}…"

    def stop(self) -> None:
        self.player.stop()
