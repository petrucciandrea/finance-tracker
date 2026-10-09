FROM python:3.12-slim

WORKDIR /app

# curl needed for the Docker healthcheck in docker-compose.yml
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# poetry.lock is required (no `*`): without it the build resolves whatever is
# newest that day, so two builds of the same commit could differ.
COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir --upgrade pip poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-root

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
