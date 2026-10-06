from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from jobseeker.llm import LLM
from jobseeker.profile.resume import extract_text

FACTS_SYSTEM = """You extract facts from a resume for later use in job applications.
Rules:
- Copy every metric exactly as written in the resume (e.g. "67%", "480K+", "84% ROC-AUC", "30,000+").
- Each achievement is one resume bullet, rewritten as one plain sentence that keeps every number.
- `metrics` lists every number or percentage that appears in that bullet, verbatim.
- Never infer, round or invent anything. If something is not in the resume, leave it out."""


class Role(BaseModel):
    title: str
    org: str
    start: str
    end: str


class Achievement(BaseModel):
    org: str
    text: str
    metrics: list[str]


class Facts(BaseModel):
    headline: str
    roles: list[Role]
    achievements: list[Achievement]
    skills: list[str]
    education: list[str]


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_facts(facts_path: Path | str) -> Facts:
    data = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    return Facts.model_validate(data["facts"])


def load_or_build_facts(llm: LLM, resume_path: Path | str, facts_path: Path | str, model: str) -> Facts:
    resume_path, facts_path = Path(resume_path), Path(facts_path)
    sha = _sha(resume_path)
    if facts_path.exists():
        data = json.loads(facts_path.read_text(encoding="utf-8"))
        if data.get("resume_sha256") == sha:
            return Facts.model_validate(data["facts"])
    text = extract_text(resume_path)
    facts = llm.json(model=model, system=FACTS_SYSTEM, prompt=f"<resume>\n{text}\n</resume>",
                     schema=Facts, effort="medium")
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.write_text(json.dumps({"resume_sha256": sha, "facts": facts.model_dump()}, indent=2),
                          encoding="utf-8")
    return facts
