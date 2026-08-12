"""Small AI-facing node index with lazy, per-node schema loading.

The full schema capture is useful as a refresh artifact, but it should never be
placed in an LLM prompt.  This module builds a compact discovery index and one
detail file per node so an extension can fetch only the selected node.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SOURCE_PATH = DATA_DIR / "weavy_node_schemas.json"
INDEX_PATH = DATA_DIR / "weavy_node_index.json"
DETAILS_DIR = DATA_DIR / "weavy_nodes"
PROVIDERS_PATH = DATA_DIR / "weavy_api_providers.json"
AI_CONTRACT_PATH = DATA_DIR / "weavy_ai_contract.json"


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _detail_key(record: dict[str, Any]) -> str:
    action = record.get("action") or {}
    action_id = action.get("id")
    if action_id:
        return str(action_id)
    name = action.get("displayName") or record.get("name") or "node"
    return re.sub(r"[^a-z0-9]+", "-", str(name).casefold()).strip("-")


def _ports(handles: Any, direction: str) -> list[dict[str, Any]]:
    side = (handles or {}).get(direction) or {}
    if isinstance(side, list):
        return []
    return [
        {
            "id": port_id,
            "type": value.get("type"),
            "required": bool(value.get("required", False)),
            **({"label": value["label"]} if value.get("label") else {}),
        }
        for port_id, value in side.items()
    ]


def _index_entry(record: dict[str, Any]) -> dict[str, Any]:
    action = record.get("action") or {}
    model = record.get("model") if isinstance(record.get("model"), dict) else {}
    name = action.get("displayName") or record.get("name") or "Unknown"
    description = action.get("description") or record.get("description") or ""
    service = model.get("service")
    key = _detail_key(record)
    search = " ".join(
        str(value)
        for value in (
            name,
            action.get("searchText"),
            action.get("icon"),
            model.get("name"),
            model.get("label"),
        )
        if value
    )
    return {
        "id": action.get("id") or key,
        "name": name,
        "description": str(description).strip()[:240],
        "nodeType": record.get("nodeType"),
        "modelKey": model.get("name"),
        "inputs": action.get("inputTypes") or [],
        "outputs": action.get("outputTypes") or [],
        "settings": list((record.get("schema") or {}).keys()),
        "configurable": bool(record.get("schema")),
        "api": {
            "gateway": "weavy",
            "upstreamService": service,
            "confidence": "explicit" if service else "not_exposed",
        },
        "schemaFile": f"weavy_nodes/{key}.json",
        "search": " ".join(sorted(_words(search))),
    }


def _detail(record: dict[str, Any]) -> dict[str, Any]:
    action = record.get("action") or {}
    model = record.get("model") if isinstance(record.get("model"), dict) else {}
    return {
        "id": action.get("id") or _detail_key(record),
        "name": action.get("displayName") or record.get("name"),
        "description": action.get("description") or record.get("description"),
        "nodeType": record.get("nodeType"),
        "version": record.get("version"),
        "action": action,
        "model": model or None,
        "api": {
            "gateway": "weavy",
            "upstreamService": model.get("service"),
            "confidence": "explicit" if model.get("service") else "not_exposed",
        },
        "ports": {
            "inputs": _ports(record.get("handles"), "input"),
            "outputs": _ports(record.get("handles"), "output"),
        },
        "defaults": record.get("params") or {},
        "settings": record.get("schema") or {},
    }


def build_registry(
    source: Path = SOURCE_PATH,
    index_path: Path = INDEX_PATH,
    details_dir: Path = DETAILS_DIR,
    providers_path: Path = PROVIDERS_PATH,
    ai_contract_path: Path = AI_CONTRACT_PATH,
) -> dict[str, Any]:
    captured = json.loads(source.read_text())
    records = [record for record in captured["nodes"] if record.get("status") == "ok"]
    details_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    services: dict[str, int] = {}
    model_count = 0
    hidden_model_count = 0
    for record in records:
        entry = _index_entry(record)
        entries.append(entry)
        detail_path = details_dir / Path(entry["schemaFile"]).name
        detail_path.write_text(json.dumps(_detail(record), separators=(",", ":")) + "\n")
        if entry["modelKey"]:
            model_count += 1
            service = entry["api"]["upstreamService"]
            if service:
                services[service] = services.get(service, 0) + 1
            else:
                hidden_model_count += 1

    entries.sort(key=lambda item: item["name"].casefold())
    index = {
        "version": 1,
        "count": len(entries),
        "usage": "Search this small index, choose one id, then load only its schemaFile.",
        "gateway": {
            "provider": "weavy",
            "baseUrl": "https://api.weavy.ai",
            "upstreamVisibility": "Only model.service values are explicit; never infer an API provider from the model brand.",
        },
        "nodes": entries,
    }
    index_path.write_text(json.dumps(index, separators=(",", ":")) + "\n")

    providers = {
        "gateway": {
            "provider": "Weavy",
            "host": "api.weavy.ai",
            "confidence": "observed_in_browser_network",
        },
        "models": model_count,
        "explicitUpstreamServices": dict(sorted(services.items())),
        "upstreamNotExposed": hidden_model_count,
        "warning": "These are serving services, not model owners. Missing values remain behind Weavy's server-side gateway.",
    }
    providers_path.write_text(json.dumps(providers, indent=2, sort_keys=True) + "\n")

    ai_contract = {
        "version": 1,
        "purpose": "Let an AI build Weavy flows without receiving the full node schema capture.",
        "instructions": [
            "Translate the user's goal into required input and output media types.",
            "Call search_nodes with a short capability query; do not request the full catalog.",
            "Choose a returned node id only after checking its inputs, outputs, and description.",
            "Call get_node_schema for that one id and validate settings against its settings object.",
            "Create the node with its action payload, apply only validated settings, then connect compatible port types.",
            "If candidates are ambiguous or required input is missing, ask the user instead of guessing.",
        ],
        "tools": [
            {
                "name": "search_nodes",
                "description": "Return a small ranked candidate list from the local compact index.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "input_type": {"type": ["string", "null"]},
                        "output_type": {"type": ["string", "null"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_node_schema",
                "description": "Load only the selected node's direct action, ports, defaults, and settings.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
        ],
        "dataFlow": "user goal -> search_nodes -> one node id -> get_node_schema -> validate -> create/connect/run",
    }
    ai_contract_path.write_text(json.dumps(ai_contract, indent=2) + "\n")
    return {
        "nodes": len(entries),
        "indexBytes": index_path.stat().st_size,
        "detailFiles": len(entries),
        "providers": providers,
        "aiContract": str(ai_contract_path),
    }


class NodeRegistry:
    """Resolve a node from the compact index and load its detail lazily."""

    def __init__(self, index_path: Path = INDEX_PATH):
        self.index_path = index_path
        self.root = index_path.parent
        self.data = json.loads(index_path.read_text())
        self.nodes: list[dict[str, Any]] = self.data["nodes"]

    def search(
        self,
        query: str,
        *,
        input_type: str | None = None,
        output_type: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        query_words = _words(query)
        normalized_query = " ".join(sorted(query_words))
        ranked = []
        for node in self.nodes:
            if input_type and input_type not in node["inputs"]:
                continue
            if output_type and output_type not in node["outputs"]:
                continue
            name = node["name"].casefold()
            haystack = f"{name} {node['search']} {node['description'].casefold()}"
            overlap = len(query_words & _words(haystack))
            score = overlap * 10
            if query.casefold() == name:
                score += 1000
            elif query.casefold() in name:
                score += 200
            elif normalized_query and normalized_query in node["search"]:
                score += 50
            if score:
                ranked.append((score, node))
        ranked.sort(key=lambda item: (-item[0], item[1]["name"].casefold()))
        return [node for _, node in ranked[:limit]]

    def get(self, reference: str) -> dict[str, Any]:
        folded = reference.casefold()
        node = next(
            (
                item
                for item in self.nodes
                if str(item["id"]).casefold() == folded or item["name"].casefold() == folded
            ),
            None,
        )
        if node is None:
            matches = self.search(reference, limit=2)
            if len(matches) != 1:
                names = ", ".join(match["name"] for match in matches) or "none"
                raise KeyError(f"Node {reference!r} is ambiguous or missing; matches: {names}")
            node = matches[0]
        return json.loads((self.root / node["schemaFile"]).read_text())
