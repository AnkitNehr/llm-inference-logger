FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY ingestion_api/requirements.txt /app/ingestion_api/requirements.txt
RUN pip install --no-cache-dir -r /app/ingestion_api/requirements.txt

COPY ingestion_api /app/ingestion_api
COPY sdk/llm_sdk /app/llm_sdk

EXPOSE 8002
CMD ["uvicorn", "ingestion_api.main:app", "--host", "0.0.0.0", "--port", "8002"]
