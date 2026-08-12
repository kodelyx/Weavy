# Weavy Backend Bridge

This is a thin Manifest V3 bridge. It contains a small status popup but no
Python, WASM, model catalog or AI. The existing Python backend remains the
source of all automation.

## Install

1. Open `chrome://extensions` and enable Developer mode.
2. Choose **Load unpacked** and select this `extension` folder.
3. Keep a signed-in `https://app.weavy.ai/` tab open.
4. Start the backend manually when needed:

   ```bash
   cd /Users/akash/Work/Figma
   python3 -m weavy.bridge_server
   ```

   Keep that terminal open. Port `8765` is for the extension and `8766` is for
   Python CLI commands. Nothing is installed into macOS startup services.

Use `python3 -m weavy.cli bridge-status` for a safe connection check. It lists
cookie metadata but deliberately hides cookie values from terminal output.

No Chrome `--remote-debugging-port=9222` flag is required.

The bridge exposes CDP commands/events for the selected Weavy tab through
`chrome.debugger`, plus cookies scoped strictly to `weavy.ai`. It cannot read
cookies for other websites or browser passwords/profile data.

Raw CDP cookie commands are blocked so they cannot bypass this domain scope.

The popup shows backend/tab/debugger status, last activity and errors. **Test
Weavy connection** performs a harmless read-only browser access check.

When a backend request arrives and no Weavy tab is open, the bridge opens
`https://app.weavy.ai/` automatically, waits for it to load, and attaches.

Flow selection is deterministic: an explicit flow ID wins, otherwise the
in-memory current flow is reused, then an open flow tab, and finally a new flow
is created only when none exists. The ID is not persisted to disk.

The localhost daemon accepts one CLI client at a time, rejects webpage-origin
WebSockets, and accepts the extension connection only from a Chrome extension
origin.
