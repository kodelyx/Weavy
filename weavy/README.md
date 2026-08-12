# Weavy backend automation

This folder contains only the reusable automation package. Experimental scripts,
logs, and tests intentionally live outside this directory.

Run from the workspace root:

```bash
python3 -m weavy.cli bridge-status
python3 -m weavy.cli inspect
python3 -m weavy.cli add Prompt
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
python3 -m weavy.cli find-node "text to video" --type video
python3 -m weavy.cli node-schema "Kling 1.6"
python3 -m weavy.cli add Prompt --flow-id aCQON7a929mNGh7DoHX8gJ
```

`add` does not open or search the left panel. It calls Weavy's internal node
factory with a captured `menuItem` action, then verifies that the resulting node
is visible and populated. `refresh-catalog` fetches all current actions once and
caches them in `data/weavy_node_actions.json`; later `add` calls stay direct.
`build-node-registry` converts the large capture into an AI-friendly compact
index plus lazy per-node detail files. An extension only needs to load the one
detail file selected by the AI.

Browser access uses the small Manifest V3 extension in `extension/`. It connects
to the Python backend on localhost and forwards debugger commands/events, so
Chrome does not need `--remote-debugging-port=9222`. Cookie access is restricted
to `weavy.ai`; other sites and browser passwords/profile data are inaccessible.

Start the bridge explicitly with `python3 -m weavy.bridge_server` and stop it
with `Ctrl+C`. The project does not install a macOS LaunchAgent or login item.
