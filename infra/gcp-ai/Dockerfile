FROM python:3.12-slim
WORKDIR /app
COPY infra/gcp-ai/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY infra/gcp-ai/gateway.py .
COPY src/delivery/meal_snapshot.py ./meal_snapshot.py
COPY data/meal-snapshot.json ./data/meal-snapshot.json
USER 65532:65532
CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8080"]
