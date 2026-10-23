"""Accounts for a private online bot: the owner plus up to 10 friends who sign up themselves.

Only on when PURPLE_PASSWORD is set (the laptop and the public demo stay open, as before). The owner signs in with
the name "owner" and PURPLE_PASSWORD (or the browser's Basic login with that password, as before). Friends register
with a name and password while seats are left (PURPLE_MAX_USERS, default 10). A friend can see the owner's Purple
Desk read-only and use the tools (build, test, paper accounts) with their own saved items, which nobody else sees.
Friends never change the bot, never use the server's AI (they connect their own free key in the browser) and never
see the admin list. Passwords are stored as scrypt hashes; sessions as SHA-256 hashes of a random cookie token.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel

from .ai.providers import ProviderError

COOKIE = "purple_session"
SESSION_DAYS = 30
OWNER_NAME = "owner"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{2,29}$")
# who is asking, for this request: None = no accounts (laptop, demo) or the server itself (live loop)
CURRENT: contextvars.ContextVar[dict | None] = contextvars.ContextVar("purple_user", default=None)
OWNER = {"id": OWNER_NAME, "name": OWNER_NAME, "role": "owner"}

# A friend may read everything except these, and may not call any of these (method, path prefix).
OWNER_ONLY = [("POST", "/api/desk"), ("GET", "/api/auth/users"), ("DELETE", "/api/auth/users")]


def max_members() -> int:
    try:
        return max(0, int(os.environ.get("PURPLE_MAX_USERS", "10")))
    except ValueError:
        return 10


def scope() -> str | None:
    """Whose saved items to show: None = everyone's (no accounts, or the server), "owner", or a friend's id."""
    u = CURRENT.get()
    return None if u is None else u["id"]


def is_member() -> bool:
    u = CURRENT.get()
    return bool(u and u["role"] == "member")


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), h)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class NoServerAI:
    """What a friend gets instead of the server's AI: nothing, with a clear way to connect their own key."""
    name, model = "none", ""
    detail = "Connect your own free AI key (Connect an AI, free Gemini works): friends' accounts don't use the bot's AI."

    def status(self) -> dict:
        return {"provider": self.name, "model": "", "available": False, "detail": self.detail}

    def complete(self, system: str, messages: list[dict]) -> str:
        raise ProviderError(self.detail)


def owner_only(method: str, path: str, query: str) -> bool:
    if method == "GET" and path == "/api/desk/review" and "save=true" in query.lower():
        return True
    return any(method == m and (path == p or path.startswith(p + "/")) for m, p in OWNER_ONLY)


class Credentials(BaseModel):
    name: str
    password: str


def install(app, db, password: str) -> None:
    """The sign-in gate (middleware) and the /api/auth routes. Call only when PURPLE_PASSWORD is set."""
    import base64

    from fastapi.responses import JSONResponse
    fails: dict[str, list[float]] = {}

    def too_many(ip: str) -> bool:
        now = time.time()
        fails[ip] = [t for t in fails.get(ip, []) if now - t < 900]
        return len(fails[ip]) >= 20

    def who(request: Request) -> dict | None:
        tok = request.cookies.get(COOKIE)
        if tok:
            s = db.get_session(token_hash(tok))
            if s:
                if s["user_id"] == OWNER_NAME:
                    return OWNER
                u = db.get_user(s["user_id"])
                if u:
                    return {"id": u["id"], "name": u["name"], "role": "member"}
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                given = base64.b64decode(auth[6:]).decode().partition(":")[2]
            except ValueError:
                given = ""
            if secrets.compare_digest(given.encode(), password.encode()):
                return OWNER
        return None

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        user = who(request)
        CURRENT.set(user)
        public = path in ("/api/health", "/api/auth/me", "/api/auth/login", "/api/auth/register", "/api/auth/logout")
        if not path.startswith("/api/") or public:
            return await call_next(request)  # the app's pages load freely; they ask for a sign-in
        if user is None:
            return JSONResponse({"detail": "Please sign in."}, status_code=401)
        if user["role"] == "member" and owner_only(request.method, path, request.url.query):
            return JSONResponse({"detail": "Only the owner can change the bot. Your account can view it and use "
                                           "the tools under More."}, status_code=403)
        return await call_next(request)

    def start_session(request: Request, response: Response, user_id: str) -> None:
        tok = secrets.token_urlsafe(32)
        until = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        db.add_session(token_hash(tok), user_id, until.isoformat(timespec="seconds"))
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"
        response.set_cookie(COOKIE, tok, max_age=SESSION_DAYS * 86400, httponly=True, secure=https, samesite="lax")

    def me_view(user: dict | None) -> dict:
        left = max(0, max_members() - db.count_users())
        return {"accounts": True, "signed_in": bool(user), "name": user["name"] if user else None,
                "role": user["role"] if user else None, "seats_left": left}

    @app.get("/api/auth/me")
    def auth_me():
        return me_view(CURRENT.get())

    @app.post("/api/auth/register")
    def auth_register(body: Credentials, request: Request, response: Response):
        if db.count_users() >= max_members():
            raise HTTPException(403, "All places are taken. Ask the owner for a place.")
        name = " ".join(body.name.split())
        if not NAME_RE.match(name) or name.lower() == OWNER_NAME:
            raise HTTPException(422, "Choose a name of 3 to 30 letters or numbers (spaces, dots, dashes allowed).")
        if len(body.password) < 8:
            raise HTTPException(422, "Use a password of at least 8 characters.")
        if db.find_user(name):
            raise HTTPException(409, "That name is taken. Choose another.")
        u = db.add_user(name, hash_password(body.password))
        start_session(request, response, u["id"])
        return me_view({"id": u["id"], "name": u["name"], "role": "member"})

    @app.post("/api/auth/login")
    def auth_login(body: Credentials, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        if too_many(ip):
            raise HTTPException(429, "Too many tries. Wait 15 minutes and try again.")
        name = " ".join(body.name.split())
        if name.lower() == OWNER_NAME:
            ok, user = secrets.compare_digest(body.password.encode(), password.encode()), OWNER
        else:
            u = db.find_user(name)
            ok = bool(u) and check_password(body.password, u["pw_hash"])
            user = {"id": u["id"], "name": u["name"], "role": "member"} if ok else None
        if not ok:
            fails.setdefault(ip, []).append(time.time())
            raise HTTPException(401, "Wrong name or password.")
        start_session(request, response, user["id"])
        return me_view(user)

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, response: Response):
        tok = request.cookies.get(COOKIE)
        if tok:
            db.delete_session(token_hash(tok))
        response.delete_cookie(COOKIE)
        return me_view(None)

    @app.get("/api/auth/users")
    def auth_users():
        return {"users": db.list_users(), "max": max_members()}

    @app.delete("/api/auth/users/{uid}")
    def auth_remove(uid: str):
        if not db.get_user(uid):
            raise HTTPException(404, "No such account.")
        db.delete_user(uid)
        return {"users": db.list_users(), "max": max_members()}
