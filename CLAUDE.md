# FPL Analytics App — Claude Onboarding

Fantasy Premier League analytics web app for data-driven transfer, captain, and team selection decisions.

## Run the App
```bash
streamlit run app.py        # http://localhost:8501
# If port busy:
streamlit run app.py --server.port 8502
```

## Full Project Detail
Read `docs/WORKFLOW.md` for current status, next priorities, architecture, and all data source details.

## Stack
- **Python 3.8** — CRITICAL: always use `List`, `Dict`, `Optional`, `Union` from `typing`. Never `list[x]` or `dict[x]` syntax.
- **Streamlit** + **Plotly** for UI/charts
- **No database** — JSON file cache with TTL in `data/cache/` (safe to delete to force cold fetch)
- All weights, thresholds, scoring constants → `config.py`

## Key Files
| File | Purpose |
|------|---------|
| `app.py` | Entry point |
| `config.py` | All constants — tune here after each GW |
| `data/processors/player_stats.py` | Central data merge (FPL + Understat + vaastav) |
| `analytics/transfer_engine.py` | Transfer scoring, ceiling model, recommendations |
| `data/fetchers/fpl_api.py` | FPL API + file cache |
| `docs/WORKFLOW.md` | Full session history, next steps, architecture detail |

## Pages (all live)
`00_my_team` · `01_dashboard` · `02_transfer_suggestions` · `03_transfer_planner` · `04_differentials` · `05_xg_underperformers` · `06_captain_picker` · `07_buy_sell` · `08_injuries` · `09_wildcard` · `10_ownership_trend` · `11_gw_history`

## Team Details
- Default team ID: **38148** ("Vicario Kart")
- GW31, rank ~1.26M, bank £0.3m

## Coding Conventions
- Analytics modules in `analytics/` — no Streamlit imports, pure Python
- Pages in `pages/` — UI only, call analytics/data functions
- Components in `components/` — reusable Plotly/Streamlit widgets
- Always use FPL terminology (GW, FDR, xG, PPM, DGW, BGW, etc.)
- Keep `docs/WORKFLOW.md` updated at end of each session

## Next Priorities
1. Fantasy Football Hub integration (awaiting credentials)
2. Bench Boost / Triple Captain chip planner
3. Mini-league tracker (enter league ID, see rival squads + rank lines)
