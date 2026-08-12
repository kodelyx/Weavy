# Weavy Backend Automation

Clean Python backend for creating and arranging nodes in Weavy AI through a
thin Chrome extension bridge.

## Structure

- `weavy/` — production Python package and CLI.
- `data/weavy_node_actions.json` — prefetched direct node/model actions.
- `data/accounts.json` — private local account data; excluded from Git.

## Commands

```bash
python3 -m weavy.cli bridge-status
python3 -m weavy.cli inspect
python3 -m weavy.cli add "ChatGPT Images 2.0"
python3 -m weavy.cli arrange
python3 -m weavy.cli connect
python3 -m weavy.cli settings
python3 -m weavy.cli set Quality high
python3 -m weavy.cli refresh-catalog
python3 -m weavy.cli create-file
python3 -m weavy.cli generate-image "A cinematic futuristic Indian city" --output data/city.png
python3 -m weavy.cli refresh-toolbox-schemas
python3 -m weavy.cli upload-file /absolute/path/to/media.png
python3 -m weavy.cli refresh-node-schemas
python3 -m weavy.cli build-node-registry
python3 -m weavy.cli find-node "high quality image generation" --type image
python3 -m weavy.cli node-schema "ChatGPT Images 2.0"
python3 -m weavy.cli add Prompt --flow-id aCQON7a929mNGh7DoHX8gJ
```

Chrome does not need a remote-debugging port. Install the thin bridge from
`extension/`, keep a signed-in Weavy tab open, and run the Python CLI normally.

## Chrome extension

An install-ready Manifest V3 bridge is in `extension/`. Open
`chrome://extensions`, enable Developer mode, choose **Load unpacked**, and
select that folder. Start `python3 -m weavy.bridge_server` manually and keep it
running while using the CLI. The extension forwards Chrome debugger
commands/events and Weavy-scoped cookie operations. Nothing is installed as a
macOS startup service. The extension contains no WASM, catalog or AI.

Flow commands accept `--flow-id`. Without it, the bridge reuses its in-memory
current flow, then an open flow tab, and creates a new flow only when none is
available. Every browser command returns `flowId`, `flowUrl`, and `result`.

Only one browser-mutating CLI command runs at a time to prevent two requests
from switching the same Chrome tab concurrently.

## AI/extension node lookup

Do not send `data/weavy_node_schemas.json` to an AI. It is the full capture used
only to rebuild derived data. Give the AI `data/weavy_node_index.json`, let it
select one node id, and then load only that entry's `schemaFile` from
`data/weavy_nodes/`. The selected detail contains the direct creation action,
ports, defaults, and model-specific settings.

`data/weavy_ai_contract.json` is the small instruction/tool contract for the AI:
search first, fetch one schema second, validate, then create/connect/run. The
155 KB index stays inside the extension and is searched locally; it is not sent
to the model. Normally the AI sees only 5-8 compact matches and one selected
schema.

All browser-side model traffic uses Weavy's `api.weavy.ai` gateway. The compact
provider report in `data/weavy_api_providers.json` records only explicit
upstream service metadata; it never mistakes a model owner for an API provider.
