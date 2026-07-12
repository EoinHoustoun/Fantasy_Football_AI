"""Local-AI layer for the FPL Analytics Hub.

Everything here runs against a local Ollama server (free, offline, private).
The single seam is `ai.llm` · pages never talk to Ollama directly. Features must
degrade gracefully when Ollama is unavailable, so the app is fully usable with no
AI infrastructure at all.
"""
