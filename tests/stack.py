# Copyright (c) 2026 NightWorksIO
"""A stand-in stack: a real HTTP server on loopback, answering as a test tells it to, recording what arrives."""

import asyncio
import hashlib
import json
import ssl
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

import trustme
from aiohttp import web

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import TracebackType

API_VERSION = 1


def envelope(kind: str, data: object, version: int = API_VERSION) -> dict[str, object]:
    """Return an envelope as lemonfiber writes one."""
    return {"api_version": version, "kind": kind, "data": data}


def problem(code: str, summary: str, **more: object) -> dict[str, object]:
    """Return an `error` envelope carrying one problem."""
    data: dict[str, object] = {
        "code": code,
        "severity": "error",
        "state": "open",
        "summary": summary,
        "meaning": "What it means.",
        "remedies": [],
        **more,
    }
    return envelope("error", data)


@dataclass(frozen=True)
class Reply:
    """One answer the stand-in gives: a status, a body, and headers."""

    status: int = 200
    body: object = None
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    delay: float = 0.0

    def encoded(self) -> tuple[bytes, str]:
        """Return the body as bytes, and the type it is."""
        if isinstance(self.body, bytes):
            return self.body, "application/octet-stream"
        if isinstance(self.body, str):
            return self.body.encode(), "text/plain; charset=utf-8"
        if self.body is None:
            return b"", "text/plain; charset=utf-8"
        return json.dumps(self.body).encode(), "application/json"


@dataclass(frozen=True)
class Streamed:
    """An event stream the stand-in sends: each chunk after its delay, then held open, then closed."""

    chunks: Sequence[tuple[float, bytes]] = ()
    hold: float = 0.0
    abort: bool = False
    """Whether the connection is cut rather than the stream ended."""
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    """Headers sent beside, or in place of, the event stream's own. The body is sent chunked, so no length."""


def event(kind: str, data: object, event_id: str | None = None, version: int = API_VERSION) -> bytes:
    """Return one server-sent event carrying an envelope, as lemonfiber writes one."""
    lines = [] if event_id is None else [f"id: {event_id}"]
    lines += [f"event: {kind}", f"data: {json.dumps(envelope(kind, data, version))}", "", ""]
    return "\n".join(lines).encode()


HEARTBEAT = b": heartbeat\n\n"


@dataclass(frozen=True)
class Arrived:
    """One request as it arrived."""

    method: str
    path: str
    query: Sequence[tuple[str, str]]
    headers: Mapping[str, str]
    body: bytes

    @property
    def url(self) -> str:
        """Return the path with its query, as it was asked for."""
        return self.path + (f"?{'&'.join(f'{k}={v}' for k, v in self.query)}" if self.query else "")


class Stack:
    """A loopback server answering each method and path with the replies it was given, in order."""

    def __init__(self, *, tls: bool = False) -> None:
        """Prepare the server, with a certificate of its own where it serves TLS."""
        self.arrived: list[Arrived] = []
        self._replies: dict[tuple[str, str], list[Reply | Streamed]] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._runner: web.AppRunner | None = None
        self._context: ssl.SSLContext | None = None
        self.pin = ""
        self.authority = b""
        if tls:
            authority = trustme.CA()
            self.authority = authority.cert_pem.bytes()
            issued = authority.issue_cert("127.0.0.1", "localhost")
            self._context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            with issued.private_key_and_cert_chain_pem.tempfile() as path:
                self._context.load_cert_chain(path)
            der = ssl.PEM_cert_to_DER_cert(issued.cert_chain_pems[0].bytes().decode())
            self.pin = hashlib.sha256(der).hexdigest()
        self.port = 0

    def reply(self, method: str, path: str, *replies: Reply | Streamed) -> None:
        """Answer a method and path with these replies in turn, the last one from then on."""
        self._replies[method, path] = list(replies)

    @property
    def url(self) -> str:
        """Return the address the stand-in is listening on."""
        scheme = "https" if self._context is not None else "http"
        return f"{scheme}://127.0.0.1:{self.port}"

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        body = await request.read()
        self.arrived.append(
            Arrived(request.method, request.path, list(request.query.items()), dict(request.headers), body),
        )
        queued = self._replies.get((request.method, request.path))
        if not queued:
            return web.Response(status=599, text="the stand-in was not told how to answer this")
        reply = queued.pop(0) if len(queued) > 1 else queued[0]
        if isinstance(reply, Streamed):
            return await self._stream(request, reply)
        if reply.delay:
            await asyncio.sleep(reply.delay)
        content, content_type = reply.encoded()
        headers = {"Content-Type": content_type, **reply.headers}
        return web.Response(status=reply.status, body=content, headers=headers)

    async def _stream(self, request: web.Request, reply: Streamed) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", **reply.headers})
        await response.prepare(request)
        for delay, chunk in reply.chunks:
            await asyncio.sleep(delay)
            await response.write(chunk)
        await asyncio.sleep(reply.hold)
        if reply.abort and request.transport is not None:
            request.transport.abort()
        return response

    async def _start(self) -> None:
        application = web.Application()
        application.router.add_route("*", "/{tail:.*}", self._handle)
        self._runner = web.AppRunner(application, access_log=None, shutdown_timeout=0.1)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0, ssl_context=self._context)
        await site.start()
        sockets = self._runner.addresses
        self.port = int(sockets[0][1])

    async def _stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def __enter__(self) -> Self:
        """Start listening."""
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._start(), self._loop).result(timeout=10)
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        """Stop listening and let the thread go."""
        asyncio.run_coroutine_threadsafe(self._stop(), self._loop).result(timeout=10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)
        self._loop.close()
