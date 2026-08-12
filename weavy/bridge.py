from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from itertools import count
from typing import Any

import websockets


class BridgeError(RuntimeError):
    pass


@dataclass
class ExtensionBridgeClient:
    """Client for the persistent local bridge daemon."""

    uri: str = "ws://127.0.0.1:8766"
    timeout: float = 35
    flow_id: str | None = None
    auto_ensure_flow: bool = True
    _ids: Any = field(init=False, repr=False)
    _socket: Any = field(init=False, default=None, repr=False)
    _waiters: dict[int, asyncio.Future] = field(init=False, default_factory=dict, repr=False)
    _events: asyncio.Queue = field(init=False, default_factory=asyncio.Queue, repr=False)
    _reader: asyncio.Task | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self._ids = count(1)
        if self.flow_id is None:
            self.flow_id = os.environ.get("WEAVY_FLOW_ID") or None

    async def __aenter__(self) -> "ExtensionBridgeClient":
        deadline = asyncio.get_running_loop().time() + 8
        last_error: Exception | None = None
        while self._socket is None:
            try:
                self._socket = await websockets.connect(self.uri, open_timeout=2)
            except Exception as exc:
                last_error = exc
                if asyncio.get_running_loop().time() >= deadline:
                    raise BridgeError(
                        "Weavy backend daemon is not running. Run: python3 -m weavy.bridge_server"
                    ) from last_error
                await asyncio.sleep(0.25)
        self._reader = asyncio.create_task(self._read_messages())
        if not self.auto_ensure_flow:
            return self
        deadline = asyncio.get_running_loop().time() + min(self.timeout, 15)
        while True:
            try:
                await self.request("flow.ensure", {"flowId": self.flow_id, "autoCreate": True})
                break
            except BridgeError as exc:
                if "extension is not connected" not in str(exc).lower() or asyncio.get_running_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.35)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._reader:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        if self._socket:
            await self._socket.close()
        for waiter in self._waiters.values():
            if not waiter.done():
                waiter.set_exception(BridgeError("Backend bridge closed"))

    async def _read_messages(self) -> None:
        try:
            async for raw in self._socket:
                message = json.loads(raw)
                if "id" in message:
                    waiter = self._waiters.pop(message["id"], None)
                    if waiter and not waiter.done():
                        if message.get("error"):
                            waiter.set_exception(BridgeError(message["error"].get("message", "Bridge request failed")))
                        else:
                            waiter.set_result(message.get("result"))
                elif message.get("event"):
                    await self._events.put(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for waiter in self._waiters.values():
                if not waiter.done():
                    waiter.set_exception(BridgeError(f"Backend bridge disconnected: {exc}"))

    async def request(self, op: str, params: dict[str, Any] | None = None) -> Any:
        if not self._socket:
            raise BridgeError("Backend bridge is not connected")
        request_id = next(self._ids)
        waiter = asyncio.get_running_loop().create_future()
        self._waiters[request_id] = waiter
        await self._socket.send(json.dumps({"id": request_id, "op": op, "params": params or {}}))
        try:
            async with asyncio.timeout(self.timeout):
                return await waiter
        finally:
            self._waiters.pop(request_id, None)

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return (await self.request("cdp.call", {"method": method, "params": params or {}})) or {}

    async def evaluate(self, expression: str) -> Any:
        result = await self.call("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
        })
        value = result.get("result", {})
        if value.get("subtype") == "error" or result.get("exceptionDetails"):
            raise BridgeError(value.get("description") or str(result.get("exceptionDetails")))
        return value.get("value")

    async def list_cookies(self) -> list[dict[str, Any]]:
        return await self.request("cookies.list")

    async def get_cookie(self, name: str, url: str = "https://app.weavy.ai/") -> dict[str, Any] | None:
        return await self.request("cookies.get", {"name": name, "url": url})

    async def set_cookie(self, **details: Any) -> dict[str, Any] | None:
        return await self.request("cookies.set", details)

    async def remove_cookie(self, name: str, url: str = "https://app.weavy.ai/") -> dict[str, Any] | None:
        return await self.request("cookies.remove", {"name": name, "url": url})

    async def next_event(self, timeout: float | None = None) -> dict[str, Any]:
        if timeout is None:
            return await self._events.get()

    async def current_flow(self) -> dict[str, Any] | None:
        return await self.request("flow.current")
        async with asyncio.timeout(timeout):
            return await self._events.get()
