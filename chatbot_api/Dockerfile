FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY chatbot_api/requirements.txt /app/chatbot_api/requirements.txt
RUN pip install --no-cache-dir -r /app/chatbot_api/requirements.txt

COPY chatbot_api /app/chatbot_api
COPY sdk/llm_sdk /app/llm_sdk

EXPOSE 8001
CMD ["uvicorn", "chatbot_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
