"""Notebook library + study tool tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cedpp.library import Library, LibraryError, clean_name
from cedpp.tutor import ClaudeStudyAssistant


def page(v=200):
    return np.full((40, 30), v, np.uint8)


def test_nested_folders_and_pages(tmp_path):
    lib = Library(tmp_path / "library")
    calc = lib.create_folder(None, "Calc III")
    mid = lib.create_folder(calc, "Midterm 1")
    week = lib.create_folder(mid, "Week 3")
    assert lib.notebooks() == [calc]
    assert lib.subfolders(mid) == [week]
    assert lib.relative(week) == "Calc III / Midterm 1 / Week 3"

    p = lib.add_page(week, page(), "Gradients", [{"tip": {"title": "Gradient"}}])
    assert p.image_path.exists()
    stored = lib.pages(week)[0]
    assert stored.title == "Gradients" and stored.comments[0]["tip"]["title"] == "Gradient"
    assert lib.page_count(calc) == 1


def test_duplicate_and_bad_names(tmp_path):
    lib = Library(tmp_path)
    lib.create_folder(None, "Bio")
    with pytest.raises(LibraryError):
        lib.create_folder(None, "Bio")
    with pytest.raises(LibraryError):
        lib.create_folder(None, "   ")
    assert clean_name("a/b:c") == "a-b-c"
    for sneaky in ("../..", "../evil", "..\\evil"):     # can't escape the library
        name = clean_name(sneaky)
        assert "/" not in name and "\\" not in name and not name.startswith(".")
    escaped = lib.create_folder(None, "../evil")
    assert escaped.resolve().parent == tmp_path.resolve()


def test_reorder_persists_and_new_pages_append(tmp_path):
    lib = Library(tmp_path)
    nb = lib.create_folder(None, "Physics")
    ids = [lib.add_page(nb, page(), f"P{i}").id for i in range(3)]
    lib.reorder(nb, [ids[2], ids[0], ids[1]])
    assert [p.title for p in lib.pages(nb)] == ["P2", "P0", "P1"]
    lib.add_page(nb, page(), "P3")
    assert [p.title for p in lib.pages(nb)] == ["P2", "P0", "P1", "P3"]


def test_delete_page_and_folder(tmp_path):
    lib = Library(tmp_path)
    nb = lib.create_folder(None, "Chem")
    sub = lib.create_folder(nb, "Lab")
    a = lib.add_page(sub, page(), "A")
    lib.add_page(sub, page(), "B")
    lib.delete_page(a)
    assert [p.title for p in lib.pages(sub)] == ["B"]
    lib.delete_folder(nb)
    assert lib.notebooks() == []
    with pytest.raises(LibraryError):
        lib.delete_folder(tmp_path)


def test_study_saves_meta_roundtrip(tmp_path):
    lib = Library(tmp_path)
    nb = lib.create_folder(None, "Calc")
    p = lib.add_page(nb, page(), "Page")
    p.meta["summary"] = {"topic": "∇f", "summary": "s", "key_points": []}
    lib.save(p)
    assert lib.pages(nb)[0].meta["summary"]["topic"] == "∇f"


def test_claude_study_requests_json_schema():
    sent = {}

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            data = {"topic": "Gradients", "summary": "About ∇f.", "key_points": ["∇f"]}
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=json.dumps(data))])

    study = ClaudeStudyAssistant(client=SimpleNamespace(beta=SimpleNamespace(messages=Messages())))
    out = study.summarize(np.full((100, 80), 255, np.uint8),
                          [{"tip": {"title": "Gradient", "recognized": "∇f"}}])
    assert out["topic"] == "Gradients"
    assert sent["output_config"]["effort"] == "medium"
    assert sent["fallbacks"] == "default"
    texts = [b["text"] for b in sent["messages"][0]["content"] if b["type"] == "text"]
    assert any("Gradient: ∇f" in t for t in texts)


# ------------------------------------------------------------------ neat + search

def _neat(transcript):
    return {"title": "", "blocks": [{"kind": "text", "text": transcript}], "transcript": transcript}


def test_neat_image_is_not_listed_as_a_page(tmp_path):
    lib = Library(tmp_path)
    nb = lib.create_folder(None, "Calc")
    p = lib.add_page(nb, page(), "Gradients")
    (p.folder / f"{p.id}_neat.png").write_bytes(b"x")
    assert [x.id for x in lib.pages(nb)] == [p.id]
    assert lib.page_count(nb) == 1
    lib.delete_page(p)
    assert not p.neat_path.exists()


def test_search_ranks_and_snippets(tmp_path):
    lib = Library(tmp_path)
    calc = lib.create_folder(None, "Calc III")
    mid = lib.create_folder(calc, "Midterm")
    a = lib.add_page(mid, page(), "Lecture 7")
    a.meta["neat"] = _neat("The gradient ∇f points uphill. Directional derivative uses the gradient.")
    lib.save(a)
    b = lib.add_page(calc, page(), "Gradient descent recap")        # title hit ranks first
    c = lib.add_page(calc, page(), "Integrals")
    c.meta["neat"] = _neat("Fubini's theorem for double integrals")
    lib.save(c)

    hits = lib.search("GRADIENT")
    assert [h.page.id for h in hits] == [b.id, a.id]
    assert hits[1].where == "Notes" and "gradient" in hits[1].snippet.lower()
    assert [h.page.id for h in lib.search("gradient uphill")] == [a.id]   # all terms required
    assert lib.search("fubini")[0].page.id == c.id
    assert lib.search("   ") == []
    assert len(lib.untranscribed()) == 1


def test_search_covers_comments_and_summary_and_accents(tmp_path):
    lib = Library(tmp_path)
    nb = lib.create_folder(None, "Bio")
    p = lib.add_page(nb, page(), "Cells", [{"tip": {"title": "Mitochondria",
                                                   "comment": "Powerhouse of the cell"}}])
    p.meta["summary"] = {"topic": "Organelles", "summary": "Café au lait spots", "key_points": []}
    lib.save(p)
    assert lib.search("powerhouse")[0].where == "Ced++ comments"
    assert lib.search("cafe")[0].page.id == p.id


def test_update_meta_merges_parallel_results(tmp_path):
    lib = Library(tmp_path)
    nb = lib.create_folder(None, "Calc")
    p = lib.add_page(nb, page(), "Page")
    stale = lib.pages(nb)[0]                     # e.g. held by the page view
    lib.update_meta(p, "neat", _neat("gradient"))
    lib.update_meta(stale, "summary", {"topic": "t", "summary": "s", "key_points": []})
    meta = lib.pages(nb)[0].meta
    assert meta["neat"]["transcript"] == "gradient" and meta["summary"]["topic"] == "t"
