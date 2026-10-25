FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"
ENV RUFF_CACHE_DIR=/tmp/ruff-cache MYPY_CACHE_DIR=/tmp/mypy-cache
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps -e . && useradd -m -u 10001 sim
COPY data ./data
COPY sql ./sql
COPY web ./web
COPY config ./config
COPY tests ./tests
COPY infra/gcp-ai/gateway.py ./infra/gcp-ai/gateway.py
COPY scripts/eval_cloud_judge.py scripts/gcp_demo.py ./scripts/
RUN mkdir -p artifacts && chown -R sim:sim /app
USER sim
EXPOSE 8000
CMD ["uvicorn", "delivery.api:app", "--host", "0.0.0.0", "--port", "8000"]
