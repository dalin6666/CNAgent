from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SESSION_SECRET", "test-session-secret-that-is-long-enough")
os.environ.setdefault("AGENT_PROVIDER", "mock")

from web.app import create_app
from web.auth import hash_password
from web.models import User


class FakeAgentService:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.reset_users: list[int] = []

    async def reply(self, *, user_id: int, message: str) -> str:
        self.messages.append((user_id, message))
        return f"agent replied: {message}"

    def reset(self, *, user_id: int) -> None:
        self.reset_users.append(user_id)


@pytest.fixture()
def agent_service() -> FakeAgentService:
    return FakeAgentService()


@pytest.fixture()
def client(tmp_path, agent_service: FakeAgentService):
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    app = create_app(
        session_secret="test-session-secret-that-is-long-enough",
        database_url=database_url,
        secure_cookies=False,
        agent_service=agent_service,
    )
    with TestClient(app) as test_client:
        with app.state.database.session_factory() as session:
            session.add(
                User(
                    username="admin",
                    password_hash=hash_password("correct-password"),
                )
            )
            session.commit()
        yield test_client


def sign_in(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "correct-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_login_page_is_available(client: TestClient) -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "登录 CNAgent" in response.text


def test_anonymous_user_is_redirected_to_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")


def test_invalid_credentials_show_generic_error(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert "账号或密码错误" in response.text


def test_login_and_logout_flow(client: TestClient) -> None:
    login_response = client.post(
        "/login",
        data={"username": "admin", "password": "correct-password"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert login_response.headers["location"].endswith("/")

    home_response = client.get("/")
    assert home_response.status_code == 200
    assert "欢迎回来，admin" in home_response.text

    logout_response = client.post("/logout", follow_redirects=False)
    assert logout_response.status_code == 303

    protected_response = client.get("/", follow_redirects=False)
    assert protected_response.status_code == 303
    assert protected_response.headers["location"].endswith("/login")


def test_chat_requires_login(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "hello"})
    assert response.status_code == 401
    assert response.json()["detail"] == "请先登录"


def test_authenticated_user_can_chat(
    client: TestClient,
    agent_service: FakeAgentService,
) -> None:
    sign_in(client)

    response = client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json() == {"answer": "agent replied: hello"}
    assert agent_service.messages == [(1, "hello")]


def test_authenticated_user_can_reset_chat(
    client: TestClient,
    agent_service: FakeAgentService,
) -> None:
    sign_in(client)

    response = client.post("/api/chat/reset")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert agent_service.reset_users == [1]


def test_health_endpoint_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
