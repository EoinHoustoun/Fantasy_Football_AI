"""UI layer · the elevated design system.

`ui.theme` is the single source of truth for the app's visual tokens and the
global-CSS injector. Pages/components import tokens from here and call
`inject_theme()` once (the app.py router does this). See docs/OVERHAUL_PLAN.md.
"""
