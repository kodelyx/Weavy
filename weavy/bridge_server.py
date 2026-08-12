from __future__ import annotations

import asyncio
import json
import signal
from itertools import count
from typing import Any

import websockets


EXTENSION_PORT = 8765
CLIENT_PORT = 8766


class BridgeDaemon:
    def __init__(self) -> None:
        self.extension: Any = None
        self.clients: set[Any] = set()
        self.pending: dict[int, tuple[Any, int]] = {}
        self.ids = count(1)
        self.active_client: Any = None

    async def extension_handler(self, socket: Any) -> None:
        origin = socket.request.headers.get("Origin")
        if not origin or not origin.startswith("chrome-extension://"):
            await socket.close(code=1008, reason="Chrome extension origin required")
            return
        if self.extension is not None:
            await self.extension.close(code=1012, reason="Extension reconnected")
        self.extension = socket
        await self.broadcast({"event": "daemon.extension", "params": {"connected": True}})
        try:
            async for raw in socket:
                message = json.loads(raw)
                if "id" in message:
                    routed = self.pending.pop(message["id"], None)
                    if routed:
                        client, original_id = routed
                        message["id"] = original_id
                        await client.send(json.dumps(message))
                elif message.get("event"):
                    await self.broadcast(message)
        finally:
            if self.extension is socket:
                self.extension = None
                for _, (client, original_id) in list(self.pending.items()):
                    await self.safe_send(client, {"id": original_id, "error": {"message": "Chrome extension disconnected"}})
                self.pending.clear()
                await self.broadcast({"event": "daemon.extension", "params": {"connected": False}})

    async def client_handler(self, socket: Any) -> None:
        origin = socket.request.headers.get("Origin")
        if origin is not None:
            await socket.close(code=1008, reason="Native localhost client required")
            return
        if self.active_client is not None:
            await socket.close(code=1013, reason="Another Weavy command is already running")
            return
        self.active_client = socket
        self.clients.add(socket)
        await self.notify_extension_clients()
        try:
            try:
                async for raw in socket:
                    message = json.loads(raw)
                    original_id = message.get("id")
                    if message.get("op") == "daemon.status":
                        await self.safe_send(socket, {"id": original_id, "result": {
                            "daemon": True, "extensionConnected": self.extension is not None,
                            "clients": len(self.clients),
                        }})
                        continue
                    if self.extension is None:
                        await self.safe_send(socket, {"id": original_id, "error": {"message": "Chrome extension is not connected"}})
                        continue
                    routed_id = next(self.ids)
                    self.pending[routed_id] = (socket, original_id)
                    message["id"] = routed_id
                    await self.extension.send(json.dumps(message))
            except websockets.ConnectionClosed:
                pass
        finally:
            self.clients.discard(socket)
            if self.active_client is socket:
                self.active_client = None
            await self.notify_extension_clients()
            for routed_id, (client, _) in list(self.pending.items()):
                if client is socket:
                    self.pending.pop(routed_id, None)

    async def safe_send(self, socket: Any, message: dict[str, Any]) -> None:
        try:
            await socket.send(json.dumps(message))
        except Exception:
            pass

    async def broadcast(self, message: dict[str, Any]) -> None:
        await asyncio.gather(*(self.safe_send(client, message) for client in list(self.clients)))

    async def notify_extension_clients(self) -> None:
        if self.extension is not None:
            await self.safe_send(self.extension, {
                "event": "daemon.clients", "params": {"count": len(self.clients)},
            })

    async def run(self) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in ("SIGTERM", "SIGINT"):
            loop.add_signal_handler(getattr(signal, name), stop.set)
        async with (
            websockets.serve(self.extension_handler, "127.0.0.1", EXTENSION_PORT),
            websockets.serve(self.client_handler, "127.0.0.1", CLIENT_PORT),
        ):
            await stop.wait()


def main() -> None:
    asyncio.run(BridgeDaemon().run())


if __name__ == "__main__":
    main()
