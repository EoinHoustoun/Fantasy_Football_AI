"""Gaffer's Briefing — a short natural-language read on the manager's gameweek.

Takes the same structured facts the Home command cards already compute (captain,
best transfer in, chip window, squad risks, deadline) and turns them into a punchy
2-3 sentence manager's briefing via the local LLM.

If Ollama is unavailable the LLM step returns None and we render a deterministic
template briefing instead — the card always shows something useful. The prompt
forbids inventing numbers: the model only rephrases the facts it is handed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ai import llm

_SYSTEM = (
    "You are an elite Fantasy Premier League assistant manager delivering a quick "
    "pre-deadline team talk. Tone: sharp, confident, encouraging, plain English. "
    "Use ONLY the facts provided — never invent players, teams, or numbers. "
    "Write 2-3 short sentences, no lists, no markdown, no headings, under 65 words."
)


def _facts_block(ctx: Dict[str, Any]) -> str:
    lines = [f"Gameweek: {ctx.get('gw', '—')}"]
    if ctx.get("deadline_text"):
        lines.append(f"Deadline: {ctx['deadline_text']}")
    if ctx.get("captain"):
        lines.append(f"Recommended captain: {ctx['captain']} ({ctx.get('captain_xp', '?')} xP)")
    if ctx.get("transfer_in"):
        lines.append(f"Top transfer target: {ctx['transfer_in']} ({ctx.get('transfer_xp', '?')} xP)")
    if ctx.get("chip"):
        lines.append(f"Chip note: {ctx['chip']}")
    if ctx.get("risks"):
        lines.append(f"Squad risks: {ctx['risks']}")
    else:
        lines.append("Squad risks: none, everyone fit")
    return "\n".join(lines)


def _has_content(ctx: Dict[str, Any]) -> bool:
    return bool(ctx.get("captain") or ctx.get("transfer_in"))


def template_briefing(ctx: Dict[str, Any]) -> Optional[str]:
    """Deterministic, instant briefing — grounded and always available (no LLM).

    Returns None only when there is genuinely nothing to say.
    """
    if not _has_content(ctx):
        return None
    parts = []
    cap = ctx.get("captain")
    if cap:
        parts.append(f"Armband looks best on {cap} ({ctx.get('captain_xp', '?')} xP) this week.")
    tin = ctx.get("transfer_in")
    if tin:
        parts.append(f"If you're moving, {tin} is the standout target.")
    if ctx.get("chip"):
        parts.append(str(ctx["chip"]).rstrip(".") + ".")
    risks = ctx.get("risks")
    parts.append(f"Watch out: {risks}." if risks else "No injury worries in your XI — set and forget.")
    return " ".join(parts)


def ai_briefing(ctx: Dict[str, Any]) -> Optional[str]:
    """LLM-written briefing. Returns None if Ollama is unavailable or the call fails.

    Latency is bounded via max_tokens; the prompt is grounded strictly in the facts.
    """
    if not _has_content(ctx):
        return None
    prompt = (
        "Here is the manager's situation for the upcoming gameweek:\n\n"
        f"{_facts_block(ctx)}\n\n"
        "Give the team talk now."
    )
    text = llm.generate(prompt, system=_SYSTEM, max_tokens=160)
    if text:
        return text.strip().strip('"')
    return None


def build_briefing(ctx: Dict[str, Any]) -> Optional[str]:
    """Best-available briefing: the LLM version if it works, else the template."""
    return ai_briefing(ctx) or template_briefing(ctx)


def used_ai() -> bool:
    """Whether the live LLM path is available (for labelling the card)."""
    return llm.is_available()
