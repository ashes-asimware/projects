FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY claim_system_adapter /app/claim_system_adapter

EXPOSE 8000

CMD ["uvicorn", "claim_system_adapter.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
