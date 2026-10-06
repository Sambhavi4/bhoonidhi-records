"""Shared fixtures for the OGC API - Records compliance suite."""
import os
import pytest
import requests

BASE = os.environ.get("RECORDS_BASE", "http://localhost:5003").rstrip("/")
COLLECTION = os.environ.get("COLLECTION_ID", "bhoonidhi")


@pytest.fixture(scope="session")
def base():
    return BASE


@pytest.fixture(scope="session")
def collection():
    return COLLECTION


@pytest.fixture(scope="session")
def get():
    """GET against the Records API, JSON by default."""
    def _get(path, params=None, timeout=90, **kw):
        p = {"f": "json"}
        p.update(params or {})
        return requests.get(f"{BASE}{path}", params=p, timeout=timeout, **kw)
    return _get


@pytest.fixture(scope="session", autouse=True)
def _service_up():
    try:
        r = requests.get(f"{BASE}/", params={"f": "json"}, timeout=30)
    except requests.RequestException as e:
        pytest.exit(f"Records API at {BASE} unreachable: {e}\n\n"
                    "start it with:  ./scripts/serve_local.sh start", 1)
    if r.status_code != 200:
        pytest.exit(f"Records API at {BASE} returned HTTP {r.status_code}\n\n"
                    "start it with:  ./scripts/serve_local.sh start", 1)
