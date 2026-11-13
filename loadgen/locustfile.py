"""Repeatable wave-shaped traffic for the SMS spam service.

Each simulated user sends ~2 req/s, so RPS ~= 2 x users.
Every request carries a deadline header (30% urgent=250 ms, 70% normal=1000 ms);
Locust counts a response slower than its deadline as a failure => failure % = deadline-miss %.
"""
import math
import os
import random
import time

from locust import HttpUser, LoadTestShape, constant_throughput, task

CORPUS_PATH = os.getenv("CORPUS", os.path.join("data", "sms_sample.txt"))
with open(CORPUS_PATH, encoding="utf-8") as f:
    CORPUS = [l.strip() for l in f if l.strip()]


class SmsUser(HttpUser):
    wait_time = constant_throughput(2)

    def on_start(self):
        # New TCP connection per request so kube-proxy spreads load onto freshly started pods
        self.client.headers["Connection"] = "close"

    @task
    def classify(self):
        deadline_ms = 250 if random.random() < 0.3 else 1000
        t0 = time.perf_counter()
        with self.client.post(
            "/classify",
            json={"text": random.choice(CORPUS)},
            headers={"X-Deadline-Ms": str(deadline_ms)},
            name="/classify",
            catch_response=True,
        ) as resp:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
            elif elapsed_ms > deadline_ms:
                resp.failure("deadline missed")


class Wave(LoadTestShape):
    """Smooth repeating wave: BASE -> PEAK -> BASE every PERIOD seconds, CYCLES times."""

    period = int(os.getenv("WAVE_PERIOD", "150"))
    cycles = int(os.getenv("WAVE_CYCLES", "3"))
    base = int(os.getenv("BASE_USERS", "5"))
    peak = int(os.getenv("PEAK_USERS", "40"))

    def tick(self):
        t = self.get_run_time()
        if t > self.period * self.cycles:
            return None
        frac = (1 - math.cos(2 * math.pi * t / self.period)) / 2
        return round(self.base + (self.peak - self.base) * frac), 10
