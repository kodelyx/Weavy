from __future__ import annotations

import argparse
import asyncio
import json
import os

from .canvas import WeavyCanvas
from .catalog import load_actions, save_actions
from .workspace import WeavyWorkspace
from .generation import WeavyGenerator
from .toolbox import ToolboxSchemaCollector
from .upload import WeavyUploader
from .schemas import NodeSchemaCollector
from .registry import NodeRegistry, build_registry
from .bridge import ExtensionBridgeClient
from pathlib import Path


async def print_flow_result(client: ExtensionBridgeClient, result: object) -> None:
    flow = await client.current_flow()
    print(json.dumps({
        "flowId": flow.get("flowId") if flow else None,
        "flowUrl": flow.get("flowUrl") if flow else None,
        "result": result,
    }, indent=2))


async def inspect_canvas() -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        await print_flow_result(client, await canvas.inspect())


async def add_node(display_name: str) -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        actions = load_actions()
        action = actions.get(display_name)
        if not action:
            available = ", ".join(sorted(actions))
            raise SystemExit(f"No direct action for {display_name!r}. Available: {available}")
        await print_flow_result(client, await canvas.add_node_direct(action))


async def refresh_catalog() -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        actions = await canvas.fetch_node_actions()
        save_actions(actions)
        await print_flow_result(client, {"saved": len(actions), "names": [a["displayName"] for a in actions]})


async def create_file() -> None:
    client, workspace = WeavyWorkspace.connect()
    async with client:
        print(json.dumps(await workspace.create_file(), indent=2))


async def generate_image(prompt: str, output: str) -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        generator = WeavyGenerator(canvas)
        await print_flow_result(client, await generator.generate_image(prompt, Path(output)))


async def refresh_toolbox_schemas() -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        result = await ToolboxSchemaCollector(canvas).collect()
        await print_flow_result(client, {"count": result["count"], "successful": result["successful"]})


async def upload_file(file_path: str) -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        await print_flow_result(client, await WeavyUploader(canvas).upload(Path(file_path)))


async def refresh_node_schemas() -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        result = await NodeSchemaCollector(canvas).collect()
        await print_flow_result(client, {"count": result["count"], "successful": result["successful"], "failed": result["failed"]})


async def arrange_canvas() -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        await print_flow_result(client, await canvas.arrange_compact())


async def connect_canvas() -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        state = await canvas.inspect()
        if len(state["nodes"]) != 2:
            raise SystemExit("Automatic connect requires exactly two nodes")
        await print_flow_result(client, await canvas.connect_nodes(state["nodes"][0]["id"], state["nodes"][1]["id"]))


async def bridge_status() -> None:
    client = ExtensionBridgeClient(auto_ensure_flow=False)
    async with client:
        bridge = await client.request("ping")
        flow = await client.request("flow.current")
        cookies = await client.list_cookies()
        print(json.dumps({
            "connected": True,
            "bridge": bridge,
            "flow": flow,
            "cookies": [
                {
                    "name": item.get("name"),
                    "domain": item.get("domain"),
                    "path": item.get("path"),
                    "secure": item.get("secure"),
                    "httpOnly": item.get("httpOnly"),
                    "session": item.get("session"),
                }
                for item in cookies
            ],
            "cookieValuesHidden": True,
        }, indent=2))


def build_node_registry() -> None:
    print(json.dumps(build_registry(), indent=2))


def find_node(query: str, media_type: str | None = None) -> None:
    print(json.dumps(NodeRegistry().search(query, output_type=media_type), indent=2))


def node_schema(reference: str) -> None:
    print(json.dumps(NodeRegistry().get(reference), indent=2))


async def model_node(canvas: WeavyCanvas) -> dict:
    state = await canvas.inspect()
    node = next((node for node in state["nodes"] if node["type"] == "custommodelV2"), None)
    if not node:
        raise SystemExit("No model node found")
    return node


async def show_settings() -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        node = await model_node(canvas)
        await print_flow_result(client, await canvas.model_settings(node["id"]))


async def set_setting(label: str, value: str) -> None:
    client, canvas = WeavyCanvas.connect()
    async with client:
        node = await model_node(canvas)
        await print_flow_result(client, await canvas.set_panel_option(node["id"], label, value))


def main() -> None:
    parser = argparse.ArgumentParser(description="Weavy automation through the Chrome extension bridge")
    parser.add_argument("command", choices=["bridge-status", "inspect", "add", "arrange", "connect", "settings", "set", "create-file", "generate-image", "upload-file", "refresh-catalog", "refresh-toolbox-schemas", "refresh-node-schemas", "build-node-registry", "find-node", "node-schema"])
    parser.add_argument("node_name", nargs="?", help="Exact Weavy menu name, such as Prompt")
    parser.add_argument("value", nargs="?", help="New setting value")
    parser.add_argument("--output", default="data/weavy_generated.png", help="Downloaded image path")
    parser.add_argument("--type", choices=["text", "image", "video", "audio", "3D"], help="Filter find-node by output type")
    parser.add_argument("--flow-id", help="Exact Weavy flow ID; otherwise use remembered/current flow or auto-create")
    args = parser.parse_args()
    if args.flow_id:
        os.environ["WEAVY_FLOW_ID"] = args.flow_id
    if args.command == "bridge-status":
        asyncio.run(bridge_status())
    elif args.command == "inspect":
        asyncio.run(inspect_canvas())
    elif args.command == "add":
        if not args.node_name:
            parser.error("add requires a node name, for example Prompt")
        asyncio.run(add_node(args.node_name))
    elif args.command == "arrange":
        asyncio.run(arrange_canvas())
    elif args.command == "connect":
        asyncio.run(connect_canvas())
    elif args.command == "settings":
        asyncio.run(show_settings())
    elif args.command == "set":
        if not args.node_name or args.value is None:
            parser.error("set requires a label and value, for example: set Quality high")
        asyncio.run(set_setting(args.node_name, args.value))
    elif args.command == "refresh-catalog":
        asyncio.run(refresh_catalog())
    elif args.command == "create-file":
        asyncio.run(create_file())
    elif args.command == "generate-image":
        if not args.node_name:
            parser.error("generate-image requires a quoted prompt")
        asyncio.run(generate_image(args.node_name, args.output))
    elif args.command == "refresh-toolbox-schemas":
        asyncio.run(refresh_toolbox_schemas())
    elif args.command == "upload-file":
        if not args.node_name:
            parser.error("upload-file requires a local file path")
        asyncio.run(upload_file(args.node_name))
    elif args.command == "refresh-node-schemas":
        asyncio.run(refresh_node_schemas())
    elif args.command == "build-node-registry":
        build_node_registry()
    elif args.command == "find-node":
        if not args.node_name:
            parser.error("find-node requires a natural-language query")
        find_node(args.node_name, args.type)
    elif args.command == "node-schema":
        if not args.node_name:
            parser.error("node-schema requires a node name or id")
        node_schema(args.node_name)


if __name__ == "__main__":
    main()
