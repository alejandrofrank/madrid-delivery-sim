FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway.py .
USER 65532:65532
CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8080"]
