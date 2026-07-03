"""LlamaCag UI — a thin PySide6 desktop client of the llama-cag-n8n v2 stack.

The app does HTTP and pixels. All inference, KV persistence, warm-up, slot
management, extraction, and registry logic lives server-side in cag-api +
llama-server (see the sibling llama-cag-n8n repo). This package never links a
local inference engine, never serialises KV state to disk, and holds no
inference state client-side.
"""

__version__ = "2.0.0"
