"""Reliable Chrome CDP automation for Weavy AI."""

from .canvas import WeavyCanvas
from .bridge import BridgeError, ExtensionBridgeClient
from .workspace import WeavyWorkspace
from .generation import WeavyGenerator
from .upload import WeavyUploader

__all__ = ["BridgeError", "ExtensionBridgeClient", "WeavyCanvas", "WeavyGenerator", "WeavyUploader", "WeavyWorkspace"]
