# Fantasy Football AI Planner

A 16-page Fantasy Premier League analytics platform that combines statistical modelling and machine learning to drive data-driven transfer, captain, and chip decisions.

## What it does

Connects to the FPL API, Understat, and football-data.co.uk to build a live player universe, then applies a composite scoring model to rank transfer targets, identify differentials, and recommend captains. Every recommendation is backed by explainable reasoning.

## Modelling & Analytics

- **Dixon-Coles team ratings** — MLE model fitted on 1,069 EPL matches (2023–26) with 16-week exponential time decay; replaces raw FPL fixture difficulty ratings
- **Composite FDR** — blends Dixon-Coles (50%) and Understat xGC/xGA (50%) into position-aware fixture difficulty scores (attack vs defence)
- **XGBoost point predictions** — trained on gameweek-level data; RMSE/MAE/R² validation
- **Exponentially weighted player form (EWM)** — rolling xGI, minutes multiplier, set-piece weighting
- **DGW/BGW detection** — applies +15% / −25% score multipliers for double/blank gameweeks
- **Ceiling model** — estimates single-GW haul potential using FPL Opta xG/xA per90 (falls back to Understat then vaastav rolling xGI)

## Pages

| Page | Description |
|------|-------------|
| My Team | Pitch view, squad table, sell candidates, captain pick |
| Dashboard | PPG by position, points-per-million scatter |
| Transfer Suggestions | #1 hero pick + reasoning, price alerts, season outlook |
| Transfer Planner | Fixture difficulty grid |
| Differentials | Low-ownership picks, bubble chart |
| xG Tracker | xG gap / haul potential |
| Captain Picker | Armband hero card, top 5 squad + differentials |
| Buy / Sell | Sell→buy pairings for every squad player |
| Injuries | Squad alerts + full league injury board |
| Wildcard Planner | Simulates optimal 15 for every remaining GW |
| Ownership Trend | Season risers/fallers, player search |
| GW History | Your score vs global average, rank chart |
| Predictions | XGBoost per-player point predictions |
| Free Hit | Optimal 15-man squad within budget for Free Hit GW |
| Chip Planner | Best GW to play Bench Boost & Triple Captain |
| Mini-League | Cumulative points, rank progression, GW-by-GW breakdown |

## Data Sources

| Source | What |
|--------|------|
| [FPL API](https://fantasy.premierleague.com/api/bootstrap-static/) | Prices, ownership, fixtures, GW stats, Opta xG per90 |
| [Understat](https://understat.com/) | Player xG/xA, team xGC/xGA |
| [vaastav](https://github.com/vaastav/Fantasy-Premier-League) | Historical FPL GW-level data |
| [football-data.co.uk](https://www.football-data.co.uk/) | Historical EPL results for Dixon-Coles |

## Setup

```bash
git clone https://github.com/EoinHoustoun/Fantasy_Football_AI.git
cd Fantasy_Football_AI
pip install -r requirements.txt
cp .env.example .env
# Add your FPL team ID to .env
streamlit run app.py
```

## Configuration

All scoring weights, thresholds, and constants are in `config.py` — tune these after each gameweek without touching the core logic.
