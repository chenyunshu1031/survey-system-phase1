import os

os.environ.setdefault("JWT_SECRET", "test-secret-only-for-local-automated-tests")

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import create_app


@pytest.fixture
def db():
    database = mongomock.MongoClient().survey_test
    database.users.create_index("usernameKey", unique=True)
    database.surveys.create_index("slug", unique=True)
    database.questions.create_index([("surveyId", 1), ("order", 1)], unique=True)
    return database


@pytest.fixture
def client(db):
    app = create_app(initialize_schema=False)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


def register_and_login(client, username="alice"):
    registered = client.post("/api/v1/auth/register", json={"username": username, "password": "password123"})
    assert registered.status_code == 201, registered.text
    logged_in = client.post("/api/v1/auth/login", json={"username": username, "password": "password123"})
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['accessToken']}"}
