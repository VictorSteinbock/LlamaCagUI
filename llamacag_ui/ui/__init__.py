"""Widgets and window composition. Presentation only — no httpx, no subprocess.

Everything slow arrives here via Qt signals from ``workers.Worker``; these
modules never touch the network or a subprocess directly. The one network module
is ``api_client``; the one subprocess module is ``stack``.
"""
