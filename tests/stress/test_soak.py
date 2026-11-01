"""Short soak test: a realistic request mix from many concurrent clients with latency SLOs."""

from __future__ import annotations

import random
import threading
import time

import pytest
import requests
from flask import Flask

from tests.stress.conftest import LiveServer, Timings, login, timed

pytestmark = pytest.mark.stress

PUBLIC_PATHS = ["/", "/blog/", "/forum/", "/services", "/about",
                "/blog/tenants-rights-getting-your-deposit-back",
                "/forum/t/landlord-keeping-my-whole-deposit-for-cleaning", "/chat/", "/healthz"]
CHAT_PROMPTS = ["my landlord won't return my deposit", "I was dismissed unfairly",
                "do I need a will?", "how do I start a company?"]


def test_mixed_traffic_soak(live_server: LiveServer, fresh_db: Flask) -> None:
    """~20 clients for ~8s: zero errors, p95 under 1.5s on the single-process dev server."""
    duration, clients = 8.0, 20
    timings = Timings()
    stop = threading.Event()
    lawyer = login(live_server, "amelia")
    client_session = login(live_server, "jordan")

    def worker(seed: int) -> int:
        rng = random.Random(seed)
        http = requests.Session()
        requests_made = 0
        while not stop.is_set():
            roll = rng.random()
            try:
                if roll < 0.55:
                    path = rng.choice(PUBLIC_PATHS)
                    response = timed(lambda: http.get(live_server.path(path), timeout=30), timings)
                elif roll < 0.75:
                    response = timed(lambda: http.post(live_server.path("/chat/api/message"),
                                                       json={"message": rng.choice(CHAT_PROMPTS)},
                                                       timeout=30), timings)
                elif roll < 0.9:
                    response = timed(lambda: lawyer.get(live_server.path("/dashboard"), timeout=30),
                                     timings)
                else:
                    response = timed(lambda: client_session.get(live_server.path("/consultations/1"),
                                                                timeout=30), timings)
                if response.status_code >= 400:
                    timings.fail(f"{response.request.method} {response.url} -> {response.status_code}")
            except requests.RequestException as exc:  # pragma: no cover - network hiccup
                timings.fail(repr(exc))
            requests_made += 1
        return requests_made

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(clients)]
    for t in threads:
        t.start()
    time.sleep(duration)
    stop.set()
    for t in threads:
        t.join(timeout=60)

    print("\nsoak:", timings.summary())
    assert not timings.failures, timings.failures[:10]
    assert len(timings.samples) > clients * 5, "throughput collapsed"
    assert timings.percentile(95) < 1.5, timings.summary()
