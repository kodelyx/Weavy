from __future__ import annotations

import json
from typing import Any

from .bridge import BridgeError as CDPError, ExtensionBridgeClient


STORE_LOOKUP = r"""
const canvas = document.querySelector('.react-flow');
if (!canvas) throw new Error('Weavy canvas not found');
const key = Object.keys(canvas).find(k => k.startsWith('__reactFiber'));
let fiber = key && canvas[key];
let store = null;
while (fiber) {
  const candidate = fiber.memoizedProps?.value;
  if (candidate?.getState && candidate?.setState) { store = candidate; break; }
  fiber = fiber.return;
}
if (!store) throw new Error('ReactFlow store not found');
"""


class WeavyCanvas:
    def __init__(self, client: ExtensionBridgeClient):
        self.client = client

    @classmethod
    def connect(cls) -> tuple[ExtensionBridgeClient, "WeavyCanvas"]:
        client = ExtensionBridgeClient()
        return client, cls(client)

    async def inspect(self) -> dict[str, Any]:
        expression = f"""(() => {{
          {STORE_LOOKUP}
          const state = store.getState();
          return {{
            nodes: (state.getNodes?.() || state.nodes || []).map(n => ({{id:n.id,type:n.type,position:n.position,data:n.data}})),
            edges: state.edges || [],
            rendered: Array.from(document.querySelectorAll('.react-flow__node')).map(n => ({{
              id:n.dataset.id, visible:getComputedStyle(n).visibility !== 'hidden', text:n.innerText
            }}))
          }};
        }})()"""
        result = await self.client.evaluate(expression)
        if not isinstance(result, dict):
            raise CDPError("Canvas inspection returned an invalid result")
        return result

    async def replace_graph(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        payload_nodes = json.dumps(nodes)
        payload_edges = json.dumps(edges)
        expression = f"""(() => {{
          {STORE_LOOKUP}
          const state = store.getState();
          state.setNodes({payload_nodes});
          state.setEdges({payload_edges});
          const updated = store.getState();
          return {{nodes: (updated.getNodes?.() || updated.nodes || []).length, edges: updated.edges.length}};
        }})()"""
        result = await self.client.evaluate(expression)
        if not isinstance(result, dict):
            raise CDPError("Graph update was not acknowledged")
        return result

    async def add_node(self, display_name: str, client_x: int = 700, client_y: int = 450) -> dict[str, Any]:
        """Add a node through Weavy's own drag/drop handler and return its live state."""
        before = await self.inspect()
        existing_ids = {node["id"] for node in before["nodes"]}
        name = json.dumps(display_name)
        expression = f"""(() => {{
          let input = document.querySelector('input[placeholder="Search"]');
          if (!input) document.querySelector('button[aria-label="search"]')?.click();
          input = document.querySelector('input[placeholder="Search"]');
          if (!input) throw new Error('Search input not found');
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
          setter.call(input, {name});
          input.dispatchEvent(new Event('input', {{bubbles:true}}));
          return true;
        }})()"""
        await self.client.evaluate(expression)

        import asyncio
        await asyncio.sleep(0.5)
        drag_expression = f"""(() => {{
          const label = Array.from(document.querySelectorAll('span')).find(el =>
            el.textContent.trim() === {name} && el.closest('[id^="left-panel-menu-item-"]'));
          const item = label?.closest('[id^="left-panel-menu-item-"]');
          const pane = document.querySelector('.react-flow__pane');
          if (!item) throw new Error('Node not found in search results: ' + {name});
          if (!pane) throw new Error('Canvas pane not found');
          const transfer = new DataTransfer();
          item.dispatchEvent(new DragEvent('dragstart', {{bubbles:true,cancelable:true,dataTransfer:transfer}}));
          pane.dispatchEvent(new DragEvent('dragover', {{bubbles:true,cancelable:true,dataTransfer:transfer,clientX:{client_x},clientY:{client_y}}}));
          pane.dispatchEvent(new DragEvent('drop', {{bubbles:true,cancelable:true,dataTransfer:transfer,clientX:{client_x},clientY:{client_y}}}));
          item.dispatchEvent(new DragEvent('dragend', {{bubbles:true,cancelable:true,dataTransfer:transfer}}));
          return [...transfer.types];
        }})()"""
        await self.client.evaluate(drag_expression)
        await asyncio.sleep(0.5)

        after = await self.inspect()
        created = [node for node in after["nodes"] if node["id"] not in existing_ids]
        if len(created) != 1:
            raise CDPError(f"Expected one new node, found {len(created)}")
        rendered = next((node for node in after["rendered"] if node["id"] == created[0]["id"]), None)
        if not rendered or not rendered["visible"] or not rendered["text"].strip():
            raise CDPError("New node exists but did not render correctly")
        return {"node": created[0], "rendered": rendered}

    async def fetch_node_actions(self) -> list[dict[str, Any]]:
        """Read every current menu action once for later direct node creation."""
        await self.client.evaluate("""(() => {
          let input = document.querySelector('input[placeholder="Search"]');
          if (!input) document.querySelector('button[aria-label="search"]')?.click();
          input = document.querySelector('input[placeholder="Search"]');
          if (!input) throw new Error('Weavy catalog panel did not open');
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
          setter.call(input, '');
          input.dispatchEvent(new Event('input', {bubbles:true}));
          return true;
        })()""")
        import asyncio
        await asyncio.sleep(1)
        actions = await self.client.evaluate("""(() => {
          const byId = new Map();
          for (const item of document.querySelectorAll('[id^="left-panel-menu-item-"][draggable="true"]')) {
            const transfer = new DataTransfer();
            item.dispatchEvent(new DragEvent('dragstart', {bubbles:true,cancelable:true,dataTransfer:transfer}));
            const raw = transfer.getData('menuItem');
            if (!raw) continue;
            try {
              const action = JSON.parse(raw);
              if (action?.id && action?.displayName) byId.set(action.id, action);
            } catch {}
          }
          document.querySelector('button[aria-label="search"]')?.click();
          return [...byId.values()].sort((a,b) => a.displayName.localeCompare(b.displayName));
        })()""")
        if not isinstance(actions, list) or not actions:
            raise CDPError("Weavy returned an empty node catalog")
        return actions

    async def add_node_direct(self, action: dict[str, Any], client_x: int = 700, client_y: int = 450) -> dict[str, Any]:
        """Call Weavy's internal node factory directly with a menuItem action."""
        before = await self.inspect()
        existing_ids = {node["id"] for node in before["nodes"]}
        payload = json.dumps(json.dumps(action))
        expression = f"""(() => {{
          const root = document.querySelector('.react-flow');
          if (!root) throw new Error('ReactFlow root not found');
          const propsKey = Object.keys(root).find(key => key.startsWith('__reactProps'));
          const onDrop = propsKey && root[propsKey]?.onDrop;
          if (typeof onDrop !== 'function') throw new Error('Weavy node factory handler not found');
          const payload = {payload};
          onDrop({{
            defaultPrevented:false,
            preventDefault() {{ this.defaultPrevented = true; }},
            clientX:{client_x}, clientY:{client_y},
            dataTransfer:{{
              files:[],
              getData(type) {{ return type.toLowerCase() === 'menuitem' ? payload : ''; }}
            }}
          }});
          return true;
        }})()"""
        await self.client.evaluate(expression)

        import asyncio
        await asyncio.sleep(0.5)
        after = await self.inspect()
        created = [node for node in after["nodes"] if node["id"] not in existing_ids]
        if len(created) != 1:
            raise CDPError(f"Expected one direct node, found {len(created)}")
        rendered = next((node for node in after["rendered"] if node["id"] == created[0]["id"]), None)
        if not rendered or not rendered["visible"] or not rendered["text"].strip():
            raise CDPError("Direct node exists but did not render correctly")
        await self.arrange_compact()
        refreshed = await self.inspect()
        created_node = next(node for node in refreshed["nodes"] if node["id"] == created[0]["id"])
        return {"node": created_node, "rendered": rendered}

    async def arrange_compact(self, gap_px: float = 90) -> list[dict[str, Any]]:
        """Drag nodes into a balanced, non-overlapping row through the app pointer handler."""
        rectangles = await self.client.evaluate("""
          Array.from(document.querySelectorAll('.react-flow__node')).map(node => {
            const rect = node.getBoundingClientRect();
            return {id:node.dataset.id,x:rect.x,y:rect.y,width:rect.width,height:rect.height};
          }).sort((a,b) => a.x - b.x || a.y - b.y)
        """)
        if not isinstance(rectangles, list):
            raise CDPError("Could not read node positions")
        if len(rectangles) < 2:
            return rectangles

        base_y = rectangles[0]["y"]
        next_x = rectangles[0]["x"] + rectangles[0]["width"] + gap_px
        for rect in rectangles[1:]:
            start_x = rect["x"] + rect["width"] / 2
            start_y = rect["y"] + 30
            target_x = next_x + rect["width"] / 2
            target_y = base_y + 30
            await self.client.call("Input.dispatchMouseEvent", {"type":"mouseMoved","x":start_x,"y":start_y})
            await self.client.call("Input.dispatchMouseEvent", {"type":"mousePressed","x":start_x,"y":start_y,"button":"left","clickCount":1})
            for step in range(1, 11):
                ratio = step / 10
                await self.client.call("Input.dispatchMouseEvent", {
                    "type":"mouseMoved", "button":"left", "buttons":1,
                    "x":start_x + (target_x - start_x) * ratio,
                    "y":start_y + (target_y - start_y) * ratio,
                })
            await self.client.call("Input.dispatchMouseEvent", {"type":"mouseReleased","x":target_x,"y":target_y,"button":"left","clickCount":1})
            next_x += rect["width"] + gap_px

        import asyncio
        await asyncio.sleep(0.5)
        return await self.client.evaluate("""
          Array.from(document.querySelectorAll('.react-flow__node')).map(node => {
            const rect = node.getBoundingClientRect();
            return {id:node.dataset.id,x:rect.x,y:rect.y,width:rect.width,height:rect.height};
          }).sort((a,b) => a.x - b.x || a.y - b.y)
        """)

    async def connect_nodes(self, source_id: str, target_id: str) -> dict[str, Any]:
        """Connect the first compatible output/input handles using real pointer events."""
        handles = await self.client.evaluate(f"""(() => {{
          const read = (nodeId, type) => Array.from(document.querySelectorAll('.react-flow__handle'))
            .filter(handle => handle.dataset.nodeid === nodeId && handle.classList.contains(type))
            .map(handle => {{
              const rect = handle.getBoundingClientRect();
              return {{id:handle.dataset.handleid,x:rect.x+rect.width/2,y:rect.y+rect.height/2}};
            }});
          return {{
            sources:read({json.dumps(source_id)}, 'source'),
            targets:read({json.dumps(target_id)}, 'target')
          }};
        }})()""")
        if not handles.get("sources") or not handles.get("targets"):
            raise CDPError("Source output or target input handle not found")
        source = handles["sources"][0]
        target = handles["targets"][0]
        await self.client.call("Input.dispatchMouseEvent", {"type":"mouseMoved","x":source["x"],"y":source["y"]})
        await self.client.call("Input.dispatchMouseEvent", {"type":"mousePressed","x":source["x"],"y":source["y"],"button":"left","clickCount":1})
        for step in range(1, 11):
            ratio = step / 10
            await self.client.call("Input.dispatchMouseEvent", {
                "type":"mouseMoved", "button":"left", "buttons":1,
                "x":source["x"] + (target["x"] - source["x"]) * ratio,
                "y":source["y"] + (target["y"] - source["y"]) * ratio,
            })
        await self.client.call("Input.dispatchMouseEvent", {"type":"mouseReleased","x":target["x"],"y":target["y"],"button":"left","clickCount":1})
        import asyncio
        await asyncio.sleep(0.5)
        state = await self.inspect()
        edge = next((edge for edge in state["edges"] if edge["source"] == source_id and edge["target"] == target_id), None)
        if not edge:
            raise CDPError("Connection was not created")
        return edge

    async def model_settings(self, node_id: str) -> dict[str, Any]:
        state = await self.inspect()
        node = next((node for node in state["nodes"] if node["id"] == node_id), None)
        if not node:
            raise CDPError(f"Node not found: {node_id}")
        data = node.get("data", {})
        schema = data.get("schema") or {}
        return {
            "nodeId": node_id,
            "name": data.get("name"),
            "values": data.get("params") or {},
            "options": {
                key: {"title": spec.get("title"), "options": spec.get("options", [])}
                for key, spec in schema.items()
            },
        }

    async def set_panel_option(self, node_id: str, label: str, value: str) -> dict[str, Any]:
        """Change a visible model dropdown through Weavy's settings panel."""
        await self.client.evaluate(f"""(() => {{
          {STORE_LOOKUP}
          store.getState().addSelectedNodes([{json.dumps(node_id)}]);
          return true;
        }})()""")
        import asyncio
        await asyncio.sleep(0.3)
        opened = await self.client.evaluate(f"""(() => {{
          const label = Array.from(document.querySelectorAll('span')).find(el => el.textContent.trim() === {json.dumps(label)});
          const button = label?.closest('.css-bozwga')?.querySelector('button');
          if (!button) return false;
          button.click();
          return true;
        }})()""")
        if not opened:
            raise CDPError(f"Visible setting not found: {label}")
        await asyncio.sleep(0.2)
        selected = await self.client.evaluate(f"""(() => {{
          const candidates = Array.from(document.querySelectorAll('span,button,div')).filter(el =>
            el.offsetParent !== null && el.children.length === 0 && el.textContent.trim() === {json.dumps(value)});
          const option = candidates[candidates.length - 1];
          if (!option) return false;
          option.click();
          return true;
        }})()""")
        if not selected:
            raise CDPError(f"Option not found for {label}: {value}")
        await asyncio.sleep(0.5)
        settings = await self.model_settings(node_id)
        key = {"Model":"model", "Quality":"quality", "Size":"size"}.get(label, label.lower())
        if str(settings["values"].get(key)).lower() != value.lower():
            raise CDPError(f"Setting did not persist: {label}={value}")
        return settings

    async def remove_node(self, node_id: str) -> bool:
        selected = await self.client.evaluate(f"""(() => {{
          {STORE_LOOKUP}
          const nodes = store.getState().getNodes?.() || [];
          if (!nodes.some(node => node.id === {json.dumps(node_id)})) return false;
          store.getState().addSelectedNodes([{json.dumps(node_id)}]);
          document.activeElement?.blur();
          document.querySelector('.react-flow')?.focus();
          return true;
        }})()""")
        if not selected:
            return False
        await self.client.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8})
        await self.client.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8})
        import asyncio
        await asyncio.sleep(0.3)
        state = await self.inspect()
        return all(node["id"] != node_id for node in state["nodes"])
