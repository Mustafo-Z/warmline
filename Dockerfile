# The API. Serves JSON only; the page is deployed separately to Vercel.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY policy ./policy
COPY agent ./agent
COPY scenarios ./scenarios

RUN pip install --no-cache-dir -e .

# Railway mounts a volume here so the demo database survives a restart.
ENV WARMLINE_DB=/data/warmline.sqlite3
ENV PORT=8000

CMD ["sh", "-c", "uvicorn warmline.api.main:app --host 0.0.0.0 --port ${PORT}"]
