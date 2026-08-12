# Figma Weavy

### The CLI toolkit for automating Weavy AI workflows from Python

[![Python 3](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Chrome Extension](https://img.shields.io/badge/Chrome-Manifest_V3-4285F4?logo=googlechrome&logoColor=white)](extension/)
[![Weavy AI](https://img.shields.io/badge/Weavy-AI_Workflows-7C3AED)](https://app.weavy.ai/)
[![GitHub stars](https://img.shields.io/github/stars/kodelyx/Weavy?style=social)](https://github.com/kodelyx/Weavy/stargazers)

**Figma Weavy** is a modular Python CLI toolkit that controls Weavy AI through
a lightweight Chrome extension bridge. Create nodes directly, configure
model-specific settings, connect workflows, upload media, run image generation,
and download results—without repeatedly searching menus or opening side panels.

> Build Weavy flows like code: fast, repeatable, and ready for AI agents.

## Why Figma Weavy?

- **Direct node creation** — add cached nodes without searching the Weavy UI.
- **Model-aware settings** — inspect and change settings exposed by each model.
- **Flow automation** — create, arrange, connect, run, and inspect workflows.
- **Media pipeline** — upload image, video, or audio files and download results.
- **Deterministic routing** — target an exact flow with `--flow-id`.
- **AI-friendly registry** — search a compact index, then load one lazy schema.
- **No CDP port** — Chrome does not need `--remote-debugging-port=9222`.
- **Privacy boundaries** — cookie access is restricted to Weavy domains.

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/kodelyx/Weavy.git
cd Weavy
```

### 2. Load the Chrome bridge

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select the `extension/` directory.
4. Sign in to [Weavy AI](https://app.weavy.ai/).

### 3. Start the local backend

```bash
python3 -m weavy.bridge_server
```

Keep that terminal running. The extension connects on port `8765`; CLI commands
connect on port `8766`.

### 4. Test the connection

```bash
python3 -m weavy.cli bridge-status
python3 -m weavy.cli inspect
```

## Build your first automated flow

```bash
# Add nodes directly—no sidebar search
python3 -m weavy.cli add Prompt
python3 -m weavy.cli add "ChatGPT Images 2.0"

# Keep the graph compact and connect its two nodes
python3 -m weavy.cli arrange
python3 -m weavy.cli connect

# Inspect model-specific options and update one
python3 -m weavy.cli settings
python3 -m weavy.cli set Quality high
```

Target an existing Weavy flow explicitly:

```bash
python3 -m weavy.cli add Prompt --flow-id YOUR_FLOW_ID
```

Without `--flow-id`, Figma Weavy reuses the current in-memory flow, then an open
flow tab, and creates a new flow only when none exists.

## CLI toolkit

| Goal | Command |
| --- | --- |
| Check bridge health | `python3 -m weavy.cli bridge-status` |
| Inspect the canvas | `python3 -m weavy.cli inspect` |
| Add a direct node | `python3 -m weavy.cli add "NODE_NAME"` |
| Arrange nodes compactly | `python3 -m weavy.cli arrange` |
| Connect two nodes | `python3 -m weavy.cli connect` |
| Read model settings | `python3 -m weavy.cli settings` |
| Change a setting | `python3 -m weavy.cli set "LABEL" "VALUE"` |
| Create a Weavy file | `python3 -m weavy.cli create-file` |
| Upload media | `python3 -m weavy.cli upload-file /absolute/path/to/media` |
| Generate an image | `python3 -m weavy.cli generate-image "PROMPT" --output result.png` |
| Refresh direct actions | `python3 -m weavy.cli refresh-catalog` |
| Search node capabilities | `python3 -m weavy.cli find-node "text to video" --type video` |
| Load one node schema | `python3 -m weavy.cli node-schema "Kling 1.6"` |
| Refresh full schemas | `python3 -m weavy.cli refresh-node-schemas` |
| Rebuild AI registry | `python3 -m weavy.cli build-node-registry` |

Run `python3 -m weavy.cli --help` for the complete command interface.

## How it works

```text
Python CLI
   │  localhost:8766
   ▼
Bridge server
   │  localhost:8765
   ▼
Chrome MV3 extension
   │  debugger access scoped to the selected Weavy tab
   ▼
Weavy canvas
```

The Python backend owns the automation logic. The small Manifest V3 extension
only transports browser commands and events. There is no Python runtime, WASM,
model catalog, or AI bundled into the extension.

When a command arrives without an open Weavy tab, the bridge opens Weavy,
waits for the canvas, and attaches automatically. Browser-mutating commands run
one at a time to prevent concurrent tab or flow switching.

## AI-agent-ready node registry

Figma Weavy avoids putting a multi-megabyte schema dump into an AI prompt:

1. Search `data/weavy_node_index.json` locally.
2. Return only a few compact candidates to the AI.
3. Select one node ID.
4. Load only its file from `data/weavy_nodes/`.
5. Validate ports and model settings before creating or connecting the node.

`data/weavy_ai_contract.json` describes this tool flow. The full
`data/weavy_node_schemas.json` remains a rebuild artifact and should not be sent
to the model.

## Project structure

```text
Weavy/
├── weavy/       # Modular Python backend and CLI
├── extension/   # Thin Chrome Manifest V3 bridge
├── data/        # Direct actions, compact index, and lazy node schemas
└── README.md
```

## Security and privacy

- Cookies are scoped strictly to `weavy.ai`.
- Raw CDP cookie commands are blocked.
- Cookie values are hidden from CLI status output.
- Webpage-origin WebSocket clients are rejected.
- Only one local CLI client can mutate the browser at a time.
- No macOS LaunchAgent, login item, or background startup service is installed.
- Local `data/accounts.json`, logs, caches, and OS metadata are excluded from Git.

## Notes

This is an independent automation toolkit and is not an official Weavy AI or
Figma product. Weavy's browser UI and internal behavior may change, so refresh
the local catalogs when nodes or models are updated.

## Support the project

If Figma Weavy saves you time, **star the repository**, share it with workflow
builders, and open an issue with ideas or bug reports.

Built by [kodelyx](https://github.com/kodelyx).
