# Build from repo root:  docker build -f app/Dockerfile -t sms-spam:v1 .
FROM python:3.11-slim
WORKDIR /srv
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/main.py .
COPY models/sms-spam-distilbert /models/sms-spam-distilbert
ENV MODEL_DIR=/models/sms-spam-distilbert HF_HUB_OFFLINE=1
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
