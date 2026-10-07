from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobseeker.config import Settings, load_preferences, load_rubric
from jobseeker.status import allowed_next
from jobseeker.web.filters import age, highlight, personal_note
from jobseeker.web.view import STEPS, TIER_LABELS, tier

HERE = Path(__file__).parent


@lru_cache(maxsize=64)
def _fingerprint(name: str, mtime_ns: int) -> str:
    return hashlib.sha1((HERE / "static" / name).read_bytes()).hexdigest()[:8]


def asset(name: str) -> str:
    """Static URL with a content fingerprint, so browsers (iPhone Safari especially) never keep a stale copy."""
    path = HERE / "static" / name
    return f"/static/{name}?v={_fingerprint(name, path.stat().st_mtime_ns)}"


class _Static(StaticFiles):
    """asset() URLs carry a content hash (?v=), so the phone may keep them forever: no re-check per page."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if b"v=" in scope.get("query_string", b"") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def create_app(settings: Settings, llm_factory=None, gmail_factory=None, contacts_deps_factory=None) -> FastAPI:
    from jobseeker.gmail.client import load_service
    from jobseeker.llm import FallbackLLM, build_llm
    from jobseeker.web import application, contacts, inbox, pipeline

    app = FastAPI(title="Job Seeker", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters.update(highlight=highlight, age=age, fromjson=json.loads, personal_note=personal_note)
    templates.env.globals["allowed_next"] = allowed_next
    templates.env.globals["asset"] = asset
    templates.env.globals.update(tier=tier, TIER_LABELS=TIER_LABELS, STEPS=STEPS)
    app.state.settings = settings
    app.state.prefs = load_preferences(settings.preferences_path)
    app.state.rubric = load_rubric(settings.rubric_path)
    app.state.templates = templates
    app.state.llm_factory = llm_factory or (
        lambda: FallbackLLM(build_llm(settings), app.state.prefs.models.fallbacks))
    app.state.gmail_factory = gmail_factory or (lambda: load_service(settings.secrets_dir / "token.json"))
    app.state.contacts_deps_factory = contacts_deps_factory or (lambda: _contacts_deps(settings, app.state.llm_factory))
    app.mount("/static", _Static(directory=HERE / "static"), name="static")
    app.add_middleware(GZipMiddleware, minimum_size=1000)  # the inbox is ~50 KB of HTML, ~8 KB gzipped
    app.include_router(inbox.router)
    app.include_router(application.router)
    app.include_router(contacts.router)
    app.include_router(pipeline.router)
    return app


def _contacts_deps(settings: Settings, llm_factory):
    from jobseeker.contacts.finder import Deps
    from jobseeker.contacts.providers import ApifyClient, HunterClient
    from jobseeker.contacts.tavily import TavilyClient

    return Deps(tavily=TavilyClient(settings.tavily_api_key) if settings.tavily_api_key else None,
                llm=llm_factory(),
                apify=ApifyClient(settings.apify_api_token) if settings.apify_api_token else None,
                hunter=HunterClient(settings.hunter_api_key) if settings.hunter_api_key else None)
