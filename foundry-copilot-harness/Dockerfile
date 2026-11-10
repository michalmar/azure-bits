FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --index-url https://packagefeedproxy.microsoft.io/pypi/simple -r requirements.lock
COPY app/ ./app/
COPY data/ ./data/
COPY prompts/ ./prompts/
COPY skills/ ./skills/
RUN useradd --uid 10001 --create-home demo
USER 10001
WORKDIR /app/app
EXPOSE 8000
CMD ["uvicorn", "main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
