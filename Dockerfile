# The Railway image (hosting plan, "Railway" runbook). Railway builds this from the connected branch.
FROM python:3.13-slim

# uv pinned to the uv_build range in pyproject.toml (>=0.11,<0.12).
COPY --from=ghcr.io/astral-sh/uv:0.11.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so a code-only change reuses this layer.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# REPO_ROOT (src/jobseeker/config.py) is /app: the code reads companies.yaml, rubric.yaml and
# config/app.example.yaml from there, so the project stays an editable install.
COPY src ./src
COPY companies.yaml rubric.yaml ./
COPY config/app.example.yaml ./config/
COPY scripts/railway/start.sh ./scripts/railway/
RUN uv sync --frozen --no-dev

# No USER line: Railway mounts the volume root-owned, so start.sh chowns /data and then drops to `app` with setpriv.
RUN useradd --system --uid 10001 --user-group --home-dir /data --no-create-home app \
    && chmod 0755 /app/scripts/railway/start.sh

ENV JOBSEEKER_HOME=/data \
    PATH=/app/.venv/bin:$PATH

CMD ["/app/scripts/railway/start.sh"]
