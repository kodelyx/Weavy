from __future__ import annotations

import asyncio
import json
import urllib.request
from pathlib import Path
from typing import Any

from .canvas import WeavyCanvas
from .bridge import BridgeError as CDPError


class WeavyGenerator:
    def __init__(self, canvas: WeavyCanvas):
        self.canvas = canvas

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        timeout: float = 180,
    ) -> dict[str, Any]:
        state = await self.canvas.inspect()
        prompt_node = next((node for node in state["nodes"] if node["type"] == "promptV3"), None)
        model_node = next((node for node in state["nodes"] if node["type"] == "custommodelV2"), None)
        if not prompt_node or not model_node:
            raise CDPError("Canvas requires one Prompt and one image model node")

        previous_ids = {
            item.get("id")
            for item in (model_node.get("data", {}).get("result") or [])
            if isinstance(item, dict)
        }
        await self._set_prompt(prompt_node["id"], prompt)
        await self._run_model(model_node["id"])

        deadline = asyncio.get_running_loop().time() + timeout
        image = None
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1)
            current = await self.canvas.inspect()
            model = next(node for node in current["nodes"] if node["id"] == model_node["id"])
            results = model.get("data", {}).get("result") or []
            image = next(
                (
                    item for item in results
                    if isinstance(item, dict)
                    and item.get("type") == "image"
                    and item.get("url")
                    and item.get("id") not in previous_ids
                ),
                None,
            )
            if image:
                break
        if not image:
            raise CDPError(f"Image generation did not finish within {timeout:g} seconds")

        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(image["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            output_path.write_bytes(response.read())
        if output_path.stat().st_size == 0:
            raise CDPError("Downloaded image is empty")

        return {
            "path": str(output_path),
            "url": image["url"],
            "width": image.get("width"),
            "height": image.get("height"),
            "bytes": output_path.stat().st_size,
            "model": model_node.get("data", {}).get("name"),
            "prompt": prompt,
        }

    async def _set_prompt(self, node_id: str, prompt: str) -> None:
        result = await self.canvas.client.evaluate(f"""(() => {{
          const editor = document.querySelector('[data-testid="rf__node-{node_id}"] .tiptap-prompt-editor');
          if (!editor) return false;
          editor.focus();
          editor.innerHTML = '<p>' + {json.dumps(prompt)} + '</p>';
          editor.dispatchEvent(new InputEvent('input', {{bubbles:true,inputType:'insertText',data:null}}));
          editor.dispatchEvent(new Event('change', {{bubbles:true}}));
          return true;
        }})()""")
        if not result:
            raise CDPError("Prompt editor was not found")
        await asyncio.sleep(0.5)

    async def _run_model(self, node_id: str) -> None:
        clicked = await self.canvas.client.evaluate(f"""(() => {{
          const node = document.querySelector('[data-testid="rf__node-{node_id}"]');
          const button = node && Array.from(node.querySelectorAll('button')).find(element =>
            element.innerText.includes('Run Model'));
          if (!button || button.disabled) return false;
          button.click();
          return true;
        }})()""")
        if not clicked:
            raise CDPError("Run Model button was unavailable")
