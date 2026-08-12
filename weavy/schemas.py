from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .canvas import WeavyCanvas
from .catalog import load_actions
from .workspace import WeavyWorkspace


NODE_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "weavy_node_schemas.json"


class NodeSchemaCollector:
    def __init__(self, canvas: WeavyCanvas):
        self.canvas = canvas

    async def collect(self) -> dict[str, Any]:
        original_url = await self.canvas.client.evaluate("location.href")
        workspace = WeavyWorkspace(self.canvas.client)
        await workspace.create_file()
        try:
            baseline_ids: set[str] = set()
            actions = list(load_actions().values())
            records = []
            for index, action in enumerate(actions, 1):
                records.append(await self._probe(action, baseline_ids))
                if index % 25 == 0 or index == len(actions):
                    print(f"schemas {index}/{len(actions)}", flush=True)

            final = await self.canvas.inspect()
            for node in final["nodes"]:
                await self.canvas.remove_node(node["id"])
            await asyncio.sleep(2)

            result = {
                "count": len(records),
                "successful": sum(record["status"] == "ok" for record in records),
                "failed": sum(record["status"] != "ok" for record in records),
                "nodes": records,
            }
            NODE_SCHEMA_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            return result
        finally:
            await self.canvas.client.call("Page.navigate", {"url": original_url})
            await asyncio.sleep(3)

    async def _probe(self, action: dict[str, Any], baseline_ids: set[str]) -> dict[str, Any]:
        before = await self.canvas.inspect()
        existing_ids = {node["id"] for node in before["nodes"]}
        payload = json.dumps(json.dumps(action))
        try:
            await self.canvas.client.evaluate(f"""(() => {{
              const root = document.querySelector('.react-flow');
              const key = Object.keys(root).find(name => name.startsWith('__reactProps'));
              const onDrop = key && root[key]?.onDrop;
              if (typeof onDrop !== 'function') throw new Error('node factory unavailable');
              const payload = {payload};
              onDrop({{
                defaultPrevented:false,
                preventDefault() {{ this.defaultPrevented=true; }},
                clientX:550, clientY:500,
                dataTransfer:{{files:[],getData(type){{return type.toLowerCase()==='menuitem'?payload:'';}}}}
              }});
              return true;
            }})()""")
            await asyncio.sleep(0.3)
            after = await self.canvas.inspect()
            created = [node for node in after["nodes"] if node["id"] not in existing_ids]
            if len(created) != 1:
                for node in created:
                    if node["id"] not in baseline_ids:
                        await self.canvas.remove_node(node["id"])
                return {"action": action, "status": "no_single_node", "created": len(created)}
            node = created[0]
            data = node.get("data", {})
            record = {
                "action": action,
                "status": "ok",
                "nodeType": node.get("type"),
                "name": data.get("name"),
                "description": data.get("description"),
                "version": data.get("version"),
                "params": data.get("params"),
                "schema": data.get("schema"),
                "handles": data.get("handles"),
                "kind": data.get("kind"),
                "menu": data.get("menu"),
                "model": data.get("model"),
            }
            if not await self.canvas.remove_node(node["id"]):
                record["cleanup"] = "failed"
            return record
        except Exception as exc:
            return {"action": action, "status": "error", "error": str(exc)}
