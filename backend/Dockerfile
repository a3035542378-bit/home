FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /srv
COPY requirements.lock ./
RUN pip install -r requirements.lock
RUN python -m playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN useradd --create-home platform && mkdir -p /srv/artifacts/browser-state /srv/artifacts/screenshots && chown -R platform:platform /srv/artifacts
USER platform
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
