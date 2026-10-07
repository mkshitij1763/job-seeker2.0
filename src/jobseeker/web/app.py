from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobseeker.config import Settings, load_preferences
from jobseeker.status import allowed_next
from jobseeker.web.filters import age, highlight, personal_note

HERE = Path(__file__).parent


def create_app(settings: Settings, llm_factory=None, gmail_factory=None, contacts_deps_factory=None) -> FastAPI:
    from jobseeker.gmail.client import load_service
    from jobseeker.llm import GroqLLM
    from jobseeker.web import application, contacts, inbox, pipeline

    app = FastAPI(title="Job Seeker", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters.update(highlight=highlight, age=age, fromjson=json.loads, personal_note=personal_note)
    templates.env.globals["allowed_next"] = allowed_next
    app.state.settings = settings
    app.state.prefs = load_preferences(settings.preferences_path)
    app.state.templates = templates
    app.state.llm_factory = llm_factory or (lambda: GroqLLM(settings.groq_api_key))
    app.state.gmail_factory = gmail_factory or (lambda: load_service(settings.secrets_dir / "token.json"))
    app.state.contacts_deps_factory = contacts_deps_factory or (lambda: _contacts_deps(settings, app.state.llm_factory))
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
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
