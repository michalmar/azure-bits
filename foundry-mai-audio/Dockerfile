FROM python:3.13-slim
ARG PIP_INDEX_URL
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock .
RUN test -n "$PIP_INDEX_URL" && python -m pip install --no-cache-dir --only-binary=:all: --index-url "$PIP_INDEX_URL" -r requirements.lock \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
COPY app/ ./
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers", "--ws-max-size", "8192"]
