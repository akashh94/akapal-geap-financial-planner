FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY app/ app/

RUN pip install --no-cache-dir .

EXPOSE 8080
# Shell form (not exec form) so bash expands ${PORT:-8080}; with exec form the
# literal string is passed to uvicorn, which rejects it as a non-integer.
CMD uvicorn app.fast_api_app:app --host 0.0.0.0 --port "${PORT:-8080}"
