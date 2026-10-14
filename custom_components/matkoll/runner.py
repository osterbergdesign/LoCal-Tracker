"""Runs the Matkoll app inside Home Assistant.

The app (the same code as the standalone server) runs on its own thread with its own event loop, so its
database work never blocks Home Assistant. Requests from the panel arrive over Home Assistant's websocket
and are passed to the app in-process, together with who the Home Assistant user is.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import threading
import uuid
from typing import Any
from urllib.parse import urlsplit

_LOGGER = logging.getLogger(__name__)


async def asgi_call(app, method: str, path: str, query: str, headers: list[tuple[str, str]], body: bytes):
    """Minimal in-process ASGI client: one request, whole response."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method.upper(),
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query.encode(),
        "root_path": "", "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "client": ("127.0.0.1", 0), "server": ("matkoll.internal", 80),
    }
    state = {"sent": False, "status": 500, "headers": [], "chunks": []}
    never = asyncio.get_running_loop().create_future()

    async def receive():
        if not state["sent"]:
            state["sent"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await never  # the request is complete; only a disconnect could follow
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
            state["headers"] = [(k.decode().lower(), v.decode()) for k, v in message.get("headers", [])]
        elif message["type"] == "http.response.body":
            state["chunks"].append(message.get("body", b""))

    try:
        await app(scope, receive, send)
    finally:
        if not never.done():
            never.cancel()
    return state["status"], dict(state["headers"]), b"".join(state["chunks"])


def _multipart(fields: dict[str, str], files: dict[str, dict]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
                     + str(value).encode() + b"\r\n")
    for name, f in files.items():
        data = base64.b64decode(f.get("data") or "")
        filename = (f.get("name") or "upload").replace('"', "")
        ctype = f.get("type") or "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class MatkollRunner:
    """Owns the Matkoll app thread."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir
        self.secret = secrets.token_hex(32)
        self.main = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    # -- lifecycle (blocking; call from an executor)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="matkoll", daemon=True)
        self._thread.start()
        if not self._ready.wait(120):
            raise RuntimeError("Matkoll didn't start within 2 minutes")
        if self._error:
            raise self._error

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            from .matkoll_app import db, main  # imported here so HA's event loop never waits on it

            db.configure(self.data_dir)
            main.TRUSTED_SECRET = self.secret
            main.startup()
            self.main = main
        except BaseException as err:  # noqa: BLE001 - reported to the caller of start()
            self._error = err
            self._ready.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    def stop(self) -> None:
        if self.main:
            try:
                self.main.shutdown()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Matkoll shutdown raised", exc_info=True)
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(10)

    # -- requests (async; call from Home Assistant's loop)

    async def request(self, user: dict[str, Any], method: str, path: str,
                      body: Any = None, form: dict | None = None) -> dict[str, Any]:
        if not self._loop or not self.main:
            raise RuntimeError("Matkoll isn't running")
        future = asyncio.run_coroutine_threadsafe(self._request(user, method, path, body, form), self._loop)
        return await asyncio.wrap_future(future)

    async def _request(self, user, method, path, body, form):
        parts = urlsplit(path)
        if not parts.path.startswith("/api/"):
            return {"status": 404, "json": {"detail": "Not found"}}
        headers = [
            ("x-matkoll-secret", self.secret),
            ("x-matkoll-ha-user", json.dumps({"id": user["id"], "name": user["name"], "admin": user["admin"]})),
        ]
        payload = b""
        if form:
            payload, ctype = _multipart(form.get("fields") or {}, form.get("files") or {})
            headers.append(("content-type", ctype))
        elif body is not None:
            payload = json.dumps(body).encode()
            headers.append(("content-type", "application/json"))
        headers.append(("content-length", str(len(payload))))
        status, resp_headers, data = await asgi_call(self.main.app, method, parts.path, parts.query, headers, payload)
        ctype = resp_headers.get("content-type", "")
        if "json" in ctype:
            try:
                return {"status": status, "json": json.loads(data or b"null")}
            except ValueError:
                pass
        return {"status": status, "json": None, "text": data.decode("utf-8", "replace")}

    # -- direct calls for sensors, calendar and actions (blocking; call from an executor)

    def call(self, name: str, *args, **kwargs):
        if not self.main:
            raise RuntimeError("Matkoll isn't running")
        return getattr(self.main, name)(*args, **kwargs)
