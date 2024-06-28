FROM python:3.12-slim As base
RUN pip install --upgrade pip

WORKDIR /app

FROM base AS builder
ENV POETRY_VERSION=1.3.1

RUN pip install "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock README.md ./

RUN poetry config virtualenvs.in-project true
RUN poetry install --only=main --no-root

COPY locust_operator ./locust_operator
RUN poetry build

FROM base AS runtime
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/dist/*.whl ./
RUN .venv/bin/pip install --no-cache-dir *.whl && rm -rf *.whl

ENV PATH="/app/.venv/bin:${PATH}"