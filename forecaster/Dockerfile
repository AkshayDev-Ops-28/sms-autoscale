# Build from repo root:  docker build -f forecaster/Dockerfile -t sms-forecaster:v1 .
FROM python:3.11-slim
WORKDIR /srv
RUN pip install --no-cache-dir numpy requests prometheus-client
COPY forecaster/forecaster.py .
CMD ["python", "forecaster.py"]
