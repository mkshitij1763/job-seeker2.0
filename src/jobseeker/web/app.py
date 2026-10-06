from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobseeker.config import Settings, load_preferences
from jobseeker.status import allowed_next
from jobseeker.web.filters import age, highlight

HERE = Path(__file__).parent


def create_app(settings: Settings, llm_factory=None, gmail_factory=None) -> FastAPI:
    from jobseeker.gmail.client import load_service
    from jobseeker.llm import GroqLLM
    from jobseeker.web import application, inbox, pipeline

    app = FastAPI(title="Job Seeker", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters.update(highlight=highlight, age=age, fromjson=json.loads)
    templates.env.globals["allowed_next"] = allowed_next
    app.state.settings = settings
    app.state.prefs = load_preferences(settings.preferences_path)
    app.state.templates = templates
    app.state.llm_factory = llm_factory or (lambda: GroqLLM(settings.groq_api_key))
    app.state.gmail_factory = gmail_factory or (lambda: load_service(settings.secrets_dir / "token.json"))
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(inbox.router)
    app.include_router(application.router)
    app.include_router(pipeline.router)
    return app
