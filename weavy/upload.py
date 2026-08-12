from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .canvas import WeavyCanvas
from .catalog import load_actions
from .bridge import BridgeError as CDPError


class WeavyUploader:
    def __init__(self, canvas: WeavyCanvas):
        self.canvas = canvas

    async def upload(self, file_path: Path, timeout: float = 60, new_node: bool = True) -> dict[str, Any]:
        path = file_path.expanduser().resolve()
        if not path.is_file():
            raise CDPError(f"Upload file not found: {path}")

        state = await self.canvas.inspect()
        node = None if new_node else next((item for item in state["nodes"] if item["type"] == "import"), None)
        if not node:
            action = load_actions().get("Import")
            if not action:
                raise CDPError("Import action is missing from the cached catalog")
            created = await self.canvas.add_node_direct(action)
            node = created["node"]
        previous_ids = {
            item.get("id")
            for item in (node.get("data", {}).get("files") or [])
            if isinstance(item, dict)
        }

        document = await self.canvas.client.call("DOM.getDocument", {"depth": -1, "pierce": True})
        found = await self.canvas.client.call(
            "DOM.querySelector",
            {
                "nodeId": document["root"]["nodeId"],
                "selector": f'[data-testid="rf__node-{node["id"]}"] input[type="file"]',
            },
        )
        if not found.get("nodeId"):
            raise CDPError("Import node file input was not found")
        await self.canvas.client.call(
            "DOM.setFileInputFiles",
            {"nodeId": found["nodeId"], "files": [str(path)]},
        )

        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            current = await self.canvas.inspect()
            import_node = next(item for item in current["nodes"] if item["id"] == node["id"])
            files = import_node.get("data", {}).get("files") or []
            uploaded = next(
                (
                    item for item in files
                    if isinstance(item, dict)
                    and item.get("id") not in previous_ids
                    and item.get("name") == path.name
                    and item.get("url")
                ),
                None,
            )
            if uploaded:
                return {"nodeId": node["id"], "localPath": str(path), "media": uploaded}
        raise CDPError(f"Upload did not finish within {timeout:g} seconds")
