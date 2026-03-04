FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi pydantic sqlalchemy azure-servicebus "uvicorn[standard]"

COPY shared /app/shared
COPY ach_ingestion_service /app/ach_ingestion_service

EXPOSE 8000

CMD ["uvicorn", "ach_ingestion_service.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
