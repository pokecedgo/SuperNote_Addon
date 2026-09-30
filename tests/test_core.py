"""Core logic tests (no device, no network). Run: pytest"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cedpp.comments import CommentStore, Status
from cedpp.config import InkConfig
from cedpp.ink import InkTracker
from cedpp.mirror import iter_images, iter_jpegs, normalize_address
from cedpp.tutor import ClaudeTutor, Tip, TutorError, TutorRequest

W, H = 600, 800


def blank():
    return np.full((H, W), 255, np.uint8)


def write(frame, x1, y1, x2, y2):
    out = frame.copy()
    out[y1:y2, x1:x2] = 20
    return out


# ------------------------------------------------------------------ mirror

def test_normalize_address_variants():
    assert normalize_address("192.168.1.42") == "http://192.168.1.42:8080/screencast.mjpeg"
    assert normalize_address("192.168.1.42:9000") == "http://192.168.1.42:9000/screencast.mjpeg"
    assert normalize_address(" http://10.0.0.5:8080/screencast.mjpeg ") == \
        "http://10.0.0.5:8080/screencast.mjpeg"
    with pytest.raises(ValueError):
        normalize_address("   ")


def test_iter_jpegs_splits_multipart_stream():
    a, b = b"\xff\xd8AAAA\xff\xd9", b"\xff\xd8BB\xff\xd9"
    body = (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + a +
            b"\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\n" + b + b"\r\n")
    assert list(iter_jpegs(io.BytesIO(body), chunk_size=5)) == [a, b]


def test_png_parts_labelled_jpeg_are_split_by_content_length():
    """Real Supernote firmware sends PNG bodies labelled image/jpeg, and PNG data
    can contain JPEG marker bytes - so parts must be split by Content-Length."""
    png1 = b"\x89PNG\r\n\x1a\n" + b"\xff\xd8junk\xff\xd9" + b"A" * 50
    png2 = b"\x89PNG\r\n\x1a\n" + b"B" * 70
    def part(body):
        return (b"--bnd\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(body)
                + body + b"\r\n")
    stream = io.BytesIO(part(png1) + part(png2) + b"--bnd--\r\n")
    ct = "multipart/x-mixed-replace; boundary=bnd"
    assert list(iter_images(stream, ct)) == [png1, png2]


def test_parts_without_content_length_split_on_boundary():
    body = b"--bnd\r\nContent-Type: image/png\r\n\r\nPNGDATA1\r\n--bnd\r\n\r\nPNGDATA2\r\n--bnd--"
    assert list(iter_images(io.BytesIO(body), 'multipart/x-mixed-replace;boundary="bnd"')) == \
        [b"PNGDATA1", b"PNGDATA2"]


# ------------------------------------------------------------------ ink tracker

def cfg(**kw):
    return InkConfig(**{**dict(pause_s=2.0, max_batch_s=100, min_cluster_cells=2), **kw})


def test_existing_ink_is_ignored_and_new_writing_fires_after_pause():
    start = write(blank(), 50, 50, 300, 70)          # already on the page
    t = InkTracker(cfg())
    t.start(start)
    frame = write(start, 100, 300, 400, 330)          # new line
    assert t.update(frame, 0.0).events == []
    upd = t.update(frame, 1.0)
    assert upd.events == [] and upd.pending_bbox is not None
    upd = t.update(frame, 2.1)
    assert len(upd.events) == 1
    x1, y1, x2, y2 = upd.events[0].bbox
    assert x1 <= 100 and x2 >= 400 and y1 <= 300 and y2 >= 330
    assert y1 > 70                                    # old heading not included
    assert t.update(frame, 5.0).events == []          # committed, not repeated


def test_still_writing_postpones_the_comment():
    t = InkTracker(cfg())
    t.start(blank())
    f = write(blank(), 100, 300, 200, 330)
    t.update(f, 0.0)
    f = write(f, 200, 300, 300, 330)                  # pen keeps moving
    assert t.update(f, 1.9).events == []
    assert t.update(f, 3.0).events == []              # only 1.1 s since last change
    assert len(t.update(f, 4.0).events) == 1


def test_separate_areas_become_separate_events():
    t = InkTracker(cfg())
    t.start(blank())
    f = write(write(blank(), 50, 100, 250, 130), 50, 500, 250, 530)
    t.update(f, 0.0)
    assert len(t.update(f, 2.5).events) == 2


def test_erase_then_rewrite_is_detected():
    t = InkTracker(cfg())
    base = write(blank(), 100, 300, 300, 330)
    t.start(base)
    t.update(blank(), 0.0)                            # erased
    rewrite = write(blank(), 100, 300, 300, 330)      # same spot again
    t.update(rewrite, 1.0)
    assert len(t.update(rewrite, 3.1).events) == 1


def test_page_turn_is_not_ink_and_reset_starts_fresh():
    t = InkTracker(cfg())
    t.start(blank())
    new_page = write(blank(), 0, 0, W, int(H * 0.5))  # half the screen changed
    assert t.update(new_page, 0.0).events == []
    assert t.update(new_page, 5.0).events == []       # still not treated as writing
    t.reset(new_page, 3)
    assert t.page_index == 3
    more = write(new_page, 100, 600, 300, 630)        # writing on the new page
    t.update(more, 6.0)
    ev = t.update(more, 9.0).events
    assert len(ev) == 1 and ev[0].page_index == 3


def _page(lines):
    f = np.full((1872, 1404), 255, np.uint8)
    for y, x1, x2 in lines:
        f[y:y + 6, x1:x2] = 20
    return f


PAGE_A = _page([(200, 100, 900), (300, 100, 700), (400, 100, 1200), (500, 100, 600)])
PAGE_B = _page([(900, 300, 1300), (1100, 200, 800), (1300, 400, 1000), (1500, 150, 1250)])


def test_page_identifier_tells_pages_apart_and_brings_old_ones_back():
    from cedpp.ink import PageIdentifier
    ids = PageIdentifier(settle_s=0.5)
    first = ids.update(PAGE_A, 0.0)
    assert first.index == 0 and first.is_new
    assert ids.update(PAGE_B, 1.0) is None            # just changed: wait to settle
    switch = ids.update(PAGE_B, 1.6)
    assert switch.index == 1 and switch.is_new
    written = PAGE_A.copy()
    written[600:606, 100:700] = 20                    # page A got a new line meanwhile
    ids.update(written, 3.0)
    back = ids.update(written, 3.6)
    assert back.index == 0 and not back.is_new       # recognised as page A again
    more = written.copy()
    more[700:706, 100:500] = 20                       # writing more is not a switch
    assert ids.update(more, 4.0) is None and ids.current == 0


def test_page_identifier_ignores_flicker():
    from cedpp.ink import PageIdentifier
    ids = PageIdentifier(settle_s=0.8)
    ids.update(PAGE_A, 0.0)
    ids.update(PAGE_B, 1.0)                           # a menu flashes up...
    assert ids.update(PAGE_A, 1.5) is None            # ...and closes: still page A
    assert ids.current == 0


def test_long_continuous_writing_gets_batched():
    t = InkTracker(cfg(max_batch_s=5.0, min_gap_s=0.5))
    t.start(blank())
    f = blank()
    events = []
    for i in range(12):                               # keeps writing every 0.4s
        f = write(f, 40 + i * 40, 300, 70 + i * 40, 330)
        events += t.update(f, i * 0.4).events
        events += t.update(f, i * 0.4 + 0.39).events
    events += t.update(f, 6.0).events
    assert len(events) >= 1


def test_not_recording_does_nothing():
    t = InkTracker(cfg())
    assert t.update(write(blank(), 0, 0, 100, 100), 10.0).events == []


# ------------------------------------------------------------------ tutor

def fake_response(payload, stop_reason="end_turn"):
    text = json.dumps(payload) if not isinstance(payload, str) else payload
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="text", text=text)])


GOOD = {"skip": False, "recognized": "∇f", "title": "Gradient", "comment": "Points uphill.",
        "extras": ["a", "b", "c", "d"], "heads_up": False}


def test_parse_response_builds_tip_and_caps_extras():
    tip = ClaudeTutor.parse_response(fake_response(GOOD))
    assert tip.title == "Gradient" and tip.extras == ["a", "b", "c"]


@pytest.mark.parametrize("resp", [fake_response(GOOD, "refusal"),
                                  fake_response("{not json"),
                                  fake_response(GOOD, "max_tokens")])
def test_parse_response_errors_are_friendly(resp):
    with pytest.raises(TutorError):
        ClaudeTutor.parse_response(resp)


def test_analyze_sends_images_schema_and_fallbacks():
    calls = {}

    class FakeMessages:
        def create(self, **kw):
            calls.update(kw)
            return fake_response(GOOD)

    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    page = write(blank(), 100, 300, 300, 330)
    tip = ClaudeTutor(client=client).analyze(
        TutorRequest(page[300:330, 100:300], page, (100, 300, 300, 330), ["Gradient: ∇f"]))
    assert tip.comment == "Points uphill."
    assert calls["model"] == "claude-opus-5"
    assert calls["fallbacks"] == "default"
    assert calls["output_config"]["format"]["type"] == "json_schema"
    blocks = calls["messages"][0]["content"]
    assert sum(b["type"] == "image" for b in blocks) == 2
    assert "Gradient: ∇f" in blocks[-1]["text"]


# ------------------------------------------------------------------ comments

def test_store_numbers_per_page_and_saves_session(tmp_path):
    s = CommentStore()
    a = s.add(0, (0, 0, 10, 10))
    b = s.add(0, (0, 20, 10, 30))
    c = s.add(1, (0, 0, 10, 10))
    assert (a.number, b.number, c.number) == (1, 2, 1)
    a.status, a.tip = Status.READY, Tip(False, "∇f", "Gradient", "Uphill.", ["x"])
    b.status = Status.SKIPPED
    assert [x.id for x in s.for_page(0)] == [a.id]
    assert s.history(0, 5) == ["Gradient: ∇f"]
    folder = s.save_session(tmp_path, {0: blank()})
    assert "Gradient" in (folder / "notes.md").read_text()
    assert (folder / "page_1.png").exists()
    saved = json.loads((folder / "comments.json").read_text())
    assert {d["status"] for d in saved} == {"ready", "pending"}


# ------------------------------------------------------------------ ask about area

def test_zone_crop_whites_out_everything_outside_the_loop():
    from cedpp.tutor.base import zone_crop
    page = np.zeros((400, 400), np.uint8)             # all ink
    loop = [(100, 100), (300, 100), (300, 300), (100, 300)]
    crop, (x1, y1, x2, y2) = zone_crop(page, loop, pad=20)
    assert (x1, y1, x2, y2) == (80, 80, 320, 320)
    assert crop[120, 120] == 0                        # inside kept
    assert crop[2, 2] == 255                          # outside the loop whited out


def test_circled_request_carries_the_question_to_claude():
    calls = {}

    class FakeMessages:
        def create(self, **kw):
            calls.update(kw)
            return fake_response(GOOD)

    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    page = blank()
    ClaudeTutor(client=client).analyze(TutorRequest(
        page[0:100, 0:100], page, (0, 0, 100, 100), requested=True,
        question="why is the gradient perpendicular?"))
    texts = [b["text"] for b in calls["messages"][0]["content"] if b["type"] == "text"]
    assert "why is the gradient perpendicular?" in texts[0]
    assert "circled" in calls["system"]


def test_zone_comment_is_saved_with_its_question(tmp_path):
    s = CommentStore()
    c = s.add(0, (0, 0, 50, 50), zone=[(0, 0), (50, 0), (50, 50)], question="what's this?")
    assert c.requested
    c.status, c.tip = Status.READY, Tip(False, "x", "Idea", "Because.", [])
    folder = s.save_session(tmp_path, {})
    saved = json.loads((folder / "comments.json").read_text())[0]
    assert saved["question"] == "what's this?" and saved["zone"][1] == [50, 0]
    assert "You asked: what's this?" in (folder / "notes.md").read_text()


def test_first_words_on_a_blank_page_are_not_a_page_switch():
    from cedpp.ink import PageIdentifier
    ids = PageIdentifier(settle_s=0.5)
    blank_page = _page([])
    ids.update(blank_page, 0.0)
    heading = _page([(150, 90, 500)])                 # first word(s) on an empty page
    assert ids.update(heading, 1.0) is None
    assert ids.update(heading, 2.0) is None and ids.current == 0
