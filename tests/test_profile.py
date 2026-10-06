import json

import fitz

from jobseeker.profile.facts import load_facts, load_or_build_facts
from jobseeker.profile.resume import extract_text
from tests.fakes import FakeLLM


def _pdf(path, text="Kshitij Meshram\nProduct Analyst at Inito\nCut errors by 67%"):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(path)


def test_extract_text(tmp_path):
    p = tmp_path / "r.pdf"
    _pdf(p)
    assert "Cut errors by 67%" in extract_text(p)


def test_facts_cached_by_resume_hash(tmp_path, facts):
    pdf, out = tmp_path / "r.pdf", tmp_path / "facts.json"
    _pdf(pdf)
    llm = FakeLLM([facts])
    assert load_or_build_facts(llm, pdf, out, "openai/gpt-oss-120b") == facts
    assert load_or_build_facts(llm, pdf, out, "openai/gpt-oss-120b") == facts
    assert len(llm.calls) == 1
    assert "Cut errors by 67%" in llm.calls[0]["prompt"]
    assert json.loads(out.read_text())["resume_sha256"]
    assert load_facts(out) == facts


def test_facts_rebuilt_when_resume_changes(tmp_path, facts):
    pdf, out = tmp_path / "r.pdf", tmp_path / "facts.json"
    _pdf(pdf)
    llm = FakeLLM([facts, facts])
    load_or_build_facts(llm, pdf, out, "m")
    _pdf(pdf, "Different resume")
    load_or_build_facts(llm, pdf, out, "m")
    assert len(llm.calls) == 2
