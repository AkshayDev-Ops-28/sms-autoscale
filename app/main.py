"""SMS spam classifier (DistilBERT) with Prometheus metrics.

Every request may carry an X-Deadline-Ms header; the service records whether
the end-to-end handling time met that deadline (sms_deadline_total).
"""
import os
import time
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_DIR = os.getenv("MODEL_DIR", "models/sms-spam-distilbert")
LABELS = ["ham", "spam"]  # model card: ham=0, spam=1
torch.set_num_threads(int(os.getenv("TORCH_THREADS", "1")))  # 1 thread/pod -> predictable per-pod capacity

REQUESTS = Counter("sms_requests_total", "Classification requests served", ["label"])
LATENCY = Histogram(
    "sms_request_seconds",
    "Handling time of /classify including thread-pool wait",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 2, 5),
)
DEADLINE = Counter("sms_deadline_total", "Requests by deadline outcome", ["outcome"])
INFLIGHT = Gauge("sms_inflight_requests", "Requests currently in flight")

state = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["tok"] = AutoTokenizer.from_pretrained(MODEL_DIR)
    state["model"] = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR).eval()
    with torch.inference_mode():  # warm-up so the first real request is not slow
        state["model"](**state["tok"]("warm up", return_tensors="pt"))
    yield


app = FastAPI(title="sms-spam", lifespan=lifespan)


class SMS(BaseModel):
    text: str


@app.middleware("http")
async def track(request: Request, call_next):
    if request.url.path != "/classify":
        return await call_next(request)
    t0 = time.perf_counter()
    INFLIGHT.inc()
    try:
        response = await call_next(request)
    finally:
        INFLIGHT.dec()
    elapsed = time.perf_counter() - t0
    LATENCY.observe(elapsed)
    try:
        deadline_ms = float(request.headers.get("x-deadline-ms", "1000"))
    except ValueError:
        deadline_ms = 1000.0
    DEADLINE.labels("met" if elapsed * 1000 <= deadline_ms else "missed").inc()
    return response


@app.post("/classify")
def classify(body: SMS):
    tok, model = state["tok"], state["model"]
    enc = tok(body.text, truncation=True, max_length=192, return_tensors="pt")
    with torch.inference_mode():
        probs = torch.softmax(model(**enc).logits, dim=-1)[0]
    idx = int(probs.argmax())
    REQUESTS.labels(LABELS[idx]).inc()
    return {"label": LABELS[idx], "score": round(float(probs[idx]), 4)}


@app.get("/healthz")
def healthz():
    if "model" not in state:
        return JSONResponse({"ready": False}, status_code=503)
    return {"ready": True}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
