from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .canvas import WeavyCanvas
from .catalog import load_actions


TOOLBOX_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "weavy_toolbox_schemas.json"


def toolbox_actions() -> list[dict[str, Any]]:
    actions = load_actions().values()
    return sorted(
        (
            action for action in actions
            if action.get("price") is None
            and isinstance(action.get("order"), (int, float))
            and action["order"] < 10_000
        ),
        key=lambda action: (action.get("order", 0), action["displayName"]),
    )


class ToolboxSchemaCollector:
    def __init__(self, canvas: WeavyCanvas):
        self.canvas = canvas

    async def collect(self) -> dict[str, Any]:
        records = []
        for action in toolbox_actions():
            records.append(await self._probe(action))
        result = {
            "count": len(records),
            "successful": sum(record["status"] == "ok" for record in records),
            "nodes": records,
        }
        TOOLBOX_SCHEMA_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    async def _probe(self, action: dict[str, Any]) -> dict[str, Any]:
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
                clientX:500, clientY:500,
                dataTransfer:{{files:[],getData(type){{return type.toLowerCase()==='menuitem'?payload:'';}}}}
              }});
              return true;
            }})()""")
            await asyncio.sleep(0.35)
            after = await self.canvas.inspect()
            created = [node for node in after["nodes"] if node["id"] not in existing_ids]
            if len(created) != 1:
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
            }
            if not await self.canvas.remove_node(node["id"]):
                record["cleanup"] = "failed"
            return record
        except Exception as exc:
            return {"action": action, "status": "error", "error": str(exc)}
