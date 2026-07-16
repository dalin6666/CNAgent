from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware

from .auth import current_user, find_user_by_username, sign_in, sign_out, verify_password
from .agent_service import AgentService
from .database import Database

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _environment_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _session_secret(explicit_secret: str | None) -> str:
    secret = explicit_secret or os.getenv("SESSION_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError(
            "SESSION_SECRET must be set to a random value of at least 32 characters."
        )
    return secret


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


def create_app(
    *,
    session_secret: str | None = None,
    database_url: str | None = None,
    secure_cookies: bool | None = None,
    agent_service: AgentService | None = None,
) -> FastAPI:
    database = Database(database_url or os.getenv("DATABASE_URL", "sqlite:///./cnagent.db"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.create_tables()
        yield

    application = FastAPI(
        title="CNAgent",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.database = database
    application.state.agent_service = agent_service or AgentService(workdir=PROJECT_ROOT)
    application.mount(
        "/static",
        StaticFiles(directory=str(BASE_DIR / "static")),
        name="static",
    )

    production = os.getenv("APP_ENV", "development").strip().lower() == "production"
    cookie_secure = (
        secure_cookies
        if secure_cookies is not None
        else _environment_flag("SESSION_COOKIE_SECURE", default=production)
    )
    if production:
        cookie_secure = True

    application.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(session_secret),
        session_cookie="cnagent_session",
        max_age=8 * 60 * 60,
        same_site="lax",
        https_only=cookie_secure,
    )

    @application.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path in {"/", "/login", "/logout", "/api/chat"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/health", response_class=JSONResponse, name="health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/login", response_class=HTMLResponse, name="login_page")
    async def login_page(request: Request) -> Response:
        if current_user(request) is not None:
            return RedirectResponse(request.url_for("home"), status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": None, "username": ""},
        )

    @application.post("/login", response_class=HTMLResponse, name="login_submit")
    async def login_submit(
        request: Request,
        username: str = Form(..., max_length=64),
        password: str = Form(..., max_length=256),
    ) -> Response:
        normalized_username = username.strip()
        user = find_user_by_username(request, normalized_username)
        valid_credentials = (
            user is not None
            and user.is_active
            and verify_password(user.password_hash, password)
        )
        if not valid_credentials:
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error": "账号或密码错误",
                    "username": normalized_username,
                },
                status_code=401,
            )

        sign_in(request, user)
        return RedirectResponse(request.url_for("home"), status_code=303)

    @application.get("/", response_class=HTMLResponse, name="home")
    async def home(request: Request) -> Response:
        user = current_user(request)
        if user is None:
            return RedirectResponse(request.url_for("login_page"), status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={"user": user},
        )

    @application.post("/api/chat", response_class=JSONResponse, name="chat")
    async def chat(request: Request, payload: ChatRequest) -> Response:
        user = current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="请先登录")

        try:
            answer = await request.app.state.agent_service.reply(
                user_id=user.id,
                message=payload.message,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Agent 调用失败：{exc}") from exc

        return JSONResponse({"answer": answer})

    @application.post("/api/chat/reset", response_class=JSONResponse, name="chat_reset")
    async def chat_reset(request: Request) -> Response:
        user = current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="请先登录")
        request.app.state.agent_service.reset(user_id=user.id)
        return JSONResponse({"status": "ok"})

    @application.post("/logout", name="logout")
    async def logout(request: Request) -> Response:
        sign_out(request)
        return RedirectResponse(request.url_for("login_page"), status_code=303)

    return application


app = create_app()
