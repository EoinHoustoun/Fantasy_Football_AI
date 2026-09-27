"""A one-line notice on pages that still rank on a pre-engine score.

Until each is rebuilt on `analytics/service.py`, the page says so and points
to the page that carries the engine's answer, so no page silently contradicts
Transfers or Captain.
"""
import streamlit as st

from ui.theme import var as V


def legacy_notice(what: str, target: str, label: str) -> None:
    st.markdown(
        f'<div style="margin:6px 0 14px;padding:10px 14px;border-radius:10px;'
        f'border:1px solid {V("line")};background:{V("card")};font-size:13px;'
        f'color:{V("muted")};">This page still ranks on {what}, not the shared '
        f'projection engine. For the engine\'s answer see <b style="color:{V("text")};">'
        f'{label}</b>.</div>', unsafe_allow_html=True)
    st.page_link(target, label="Open %s →" % label)
