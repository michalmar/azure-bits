FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY static ./static

RUN useradd --create-home --home-dir /home/appuser --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app /home/appuser

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
