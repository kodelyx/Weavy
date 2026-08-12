from __future__ import annotations

import asyncio
from typing import Any

from .bridge import BridgeError as CDPError, ExtensionBridgeClient


class WeavyWorkspace:
    def __init__(self, client: ExtensionBridgeClient):
        self.client = client

    @classmethod
    def connect(cls) -> tuple[ExtensionBridgeClient, "WeavyWorkspace"]:
        client = ExtensionBridgeClient(auto_ensure_flow=False)
        return client, cls(client)

    async def create_file(self) -> dict[str, Any]:
        result = await self.client.request("flow.create")
        for _ in range(60):
            await asyncio.sleep(0.25)
            state = await self.client.evaluate("""({
              url:location.href, title:document.title,
              canvas:Boolean(document.querySelector('.react-flow'))
            })""")
            if state["canvas"]:
                return {**result, **state}
        raise CDPError("New flow was created but its canvas did not become ready")
