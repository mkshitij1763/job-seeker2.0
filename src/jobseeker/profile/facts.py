from __future__ import annotations

from pydantic import BaseModel

from jobseeker.llm import LLM

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


def extract_facts(llm: LLM, text: str, model: str) -> Facts:
    return llm.json(model=model, system=FACTS_SYSTEM, prompt=f"<resume>\n{text}\n</resume>", schema=Facts,
                    effort="medium")
