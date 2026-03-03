FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.in-project true

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-interaction

COPY README.md ./
COPY app/ app/
RUN poetry install --only main --no-interaction

# ---------------------------------------------------------------------------

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
