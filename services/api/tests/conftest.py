import os
import tempfile

# Tests never read the real data folder or its .env (API keys, database, resumes).
os.environ["APPLYPILOT_HOME"] = tempfile.mkdtemp(prefix="applypilot-home-")
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["DEMO_MODE"] = "true"
# Many tests create several accounts; test_security.py covers the closed default.
os.environ["ALLOW_REGISTRATION"] = "true"
os.environ["JOB_BOARD_TOKENS"] = ""
os.environ["PUBLIC_JOB_SOURCES"] = "false"
os.environ["AI_PROVIDER"] = "none"
# Environment variables beat .env files, so a stray .env can never lend tests a real key.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["ADZUNA_APP_ID"] = ""
os.environ["ADZUNA_APP_KEY"] = ""
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="applypilot-")
os.environ["CELERY_ENABLED"] = "false"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["AUTOAPPLY_HEADLESS"] = "true"

import pytest
from fastapi.testclient import TestClient

from app.core.database import engine
from app.main import app
from app.models import Base


@pytest.fixture(autouse=True)
def fresh_database():
    from app.core import ratelimit

    ratelimit.reset()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_header(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "jordan@example.com", "password": "correct-horse", "full_name": "Jordan Lee"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}
