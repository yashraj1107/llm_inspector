# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Copy package source first (layer-cached separately from deps)
COPY pyproject.toml ./
COPY llm_inspector/ ./llm_inspector/

# Upgrade pip + setuptools first (python:3.11-slim ships with older versions
# that lack setuptools.build_meta editable-install support)
RUN pip install --no-cache-dir --upgrade pip setuptools

# Install the package in editable mode + optional SDKs used by tests
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir openai python-dotenv

# Copy the Docker-specific test script
COPY docker_test_script.py ./

# No API keys baked in — pass them at runtime via -e or a volume-mounted .env
# Default entrypoint keeps it flexible (caller passes the full command)
