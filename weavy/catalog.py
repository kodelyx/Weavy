"""Known and prefetched Weavy menu actions used by the internal node factory."""

import json
from pathlib import Path
from typing import Any


CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "weavy_node_actions.json"


PROMPT: dict[str, Any] = {
    "id": "jzXJ8QEfxQm2sZfvzu7q",
    "displayName": "Prompt",
    "description": None,
    "icon": "prompt",
    "searchText": "prompt  ",
    "inputTypes": [],
    "outputTypes": ["text"],
    "isLeaf": True,
    "isNew": None,
    "order": 10,
    "isVerified": False,
    "termsUrls": [],
    "isByok": False,
}

CHATGPT_IMAGES_2: dict[str, Any] = {
    "id": "zeSQQxxjcaVdWWunD60J1",
    "displayName": "ChatGPT Images 2.0",
    "description": "Generate images with OpenAI's GPT Image 2",
    "icon": "openai",
    "searchText": "chatgpt images 2.0  ",
    "inputTypes": ["text"],
    "outputTypes": ["image"],
    "isLeaf": True,
    "price": 9,
    "fullPrice": 9,
    "isNew": False,
    "order": 630,
    "name": "gpt_image_1",
    "isVerified": True,
    "termsUrls": [],
    "privacyPolicyUrl": None,
    "isByok": False,
    "isPerSecond": False,
}

NODE_ACTIONS = {
    "Prompt": PROMPT,
    "ChatGPT Images 2.0": CHATGPT_IMAGES_2,
}


def load_actions() -> dict[str, dict[str, Any]]:
    actions = dict(NODE_ACTIONS)
    if CACHE_PATH.exists():
        cached = json.loads(CACHE_PATH.read_text())
        actions.update({item["displayName"]: item for item in cached if item.get("displayName")})
    return actions


def save_actions(actions: list[dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(actions, indent=2, sort_keys=True) + "\n")
