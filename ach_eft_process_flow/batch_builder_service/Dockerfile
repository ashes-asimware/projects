FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY batch_builder_service /app/batch_builder_service

EXPOSE 8000

CMD ["uvicorn", "batch_builder_service.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
