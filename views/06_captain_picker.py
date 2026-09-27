"""
Captain Picker · GW recommendation for who to captain.

Shows:
  • Hero card for the #1 captain pick (with armband graphic)
  • Top 5 captain options from your squad with score breakdown
  • Top 5 differential captain options (low-ownership players with high ceiling)
"""

import streamlit as st
from ui.page import section as _sec

from components.loading import LINES_GENERIC, LINES_SQUAD, fpl_loader
from ui import charts, theme
import pandas as pd
from typing import Optional, List, Dict, Any

from components.badges import render_badges
from components.team_identity import face_html, shirt_html, team_color

# set_page_config is owned by the app.py router (st.navigation)

SHIRT_BASE = "https://fantasy.premierleague.com/dist/img/shirts/standard"
POS_COLORS = {"GKP": "var(--ff-mint)", "DEF": "var(--ff-cyan)", "MID": "var(--ff-mag)", "FWD": "#ff6900"}


# ── Data helpers ──────────────────────────────────────────────────────────────

def load_universe():
    """Shared loader · see data/universe.py. Was a per-page copy with its own TTL."""
    from analytics import freshness
    from data.fetchers.fpl_api import fetch_bootstrap
    from data.universe import load_universe as _shared
    bs = fetch_bootstrap()
    return _shared(freshness.inputs_stamp()), bs


@st.cache_data(ttl=1800, show_spinner=False)
def load_squad(team_id: int, gw: int):
    from data.fetchers.fpl_api import get_team_squad, fetch_bootstrap
    bs = fetch_bootstrap()
    squad_df, _ = get_team_squad(team_id, gw, bootstrap=bs)
    return squad_df


def get_next_gw(bootstrap: dict) -> int:
    for e in bootstrap["events"]:
        if e.get("is_next"):
            return e["id"]
    # fallback: current + 1
    for e in bootstrap["events"]:
        if e.get("is_current"):
            return e["id"] + 1
    return 1


def get_next_gw_fdr(bootstrap: dict, fixtures_raw: list, captain_gw: int) -> Dict[int, float]:
    """Return {team_id: fdr} for the captain GW specifically."""
    from data.fetchers.fpl_api import get_fixtures_df
    fixtures_df = get_fixtures_df(fixtures_raw, bootstrap)
    gw_fix = fixtures_df[fixtures_df["gameweek"] == captain_gw]
    fdr_map = {}
    for _, row in gw_fix.iterrows():
        fdr_map[int(row["home_team_id"])] = float(row["home_fdr"])
        fdr_map[int(row["away_team_id"])] = float(row["away_fdr"])
    return fdr_map


def score_captains(players_df: pd.DataFrame, fdr_map: Dict[int, float]) -> pd.DataFrame:
    """Compute a captain_score for each player."""
    df = players_df.copy()

    df["next_gw_fdr"] = df["team_id"].map(fdr_map).fillna(3.0)
    df["has_fixture"] = df["team_id"].map(lambda t: t in fdr_map)

    # Zero out players with no fixture (BGW)
    df.loc[~df["has_fixture"], "next_gw_fdr"] = 5.0

    # Components (all 0-1)
    def norm(s):
        mn, mx = s.min(), s.max()
        if mx == mn:
            return pd.Series(0.5, index=s.index)
        return (s - mn) / (mx - mn)

    df["c_form"]    = norm(df["form"].fillna(0).astype(float))
    df["c_fixture"] = norm(5.0 - df["next_gw_fdr"])          # low FDR = good
    df["c_xg"]      = norm(df["fpl_xgi_per90"].fillna(0).astype(float))

    # ── Minutes multiplier (not just a component · scales the whole score) ────
    # Use avg_minutes from DEFCON stats when available, else estimate from totals.
    if "avg_minutes" in df.columns and df["avg_minutes"].notna().any():
        avg_mins = df["avg_minutes"].fillna(45.0).clip(0, 90)
    else:
        gws_est = max(1, int(df["minutes"].max() / 90))
        avg_mins = (df["minutes"].fillna(0) / gws_est).clip(0, 90)

    df["c_minutes"]       = (avg_mins / 90.0).round(3)          # kept for display
    df["mins_multiplier"] = ((avg_mins / 90.0) ** 0.5).clip(lower=0.45, upper=1.0)

    # ── Set piece bonus (before multiplier · penalty taker gets captain boost) ─
    import numpy as np
    _nan = pd.Series(float("nan"), index=df.index)
    pen_order = pd.to_numeric(
        df["penalties_order"] if "penalties_order" in df.columns else _nan, errors="coerce"
    )
    df["c_setpiece"] = (
        pen_order.eq(1).fillna(False).astype(float) * 0.10 +
        pen_order.eq(2).fillna(False).astype(float) * 0.04
    )

    # DGW bonus
    dgw_mult = (
        df.get("has_dgw", pd.Series(False, index=df.index))
          .map({True: 1.20, False: 1.0})
          .fillna(1.0)
    )

    # Fixture-weighted captain score: fixture is the strongest influence,
    # followed by form, then xGI. Set-piece bonus stacks on top.
    base_score = (
        df["c_fixture"]  * 0.50 +
        df["c_form"]     * 0.30 +
        df["c_xg"]       * 0.20 +
        df["c_setpiece"]
    )
    df["captain_score"] = (base_score * df["mins_multiplier"] * dgw_mult).round(4)

    # Players with no fixture cannot be captained (blank GW)
    df.loc[~df["has_fixture"], "captain_score"] = 0.0

    return df


# ── HTML components ────────────────────────────────────────────────────────────

def _shirt_url(team_code: int, is_gkp: bool) -> str:
    suffix = "_1" if is_gkp else ""
    return f"{SHIRT_BASE}/shirt_{team_code}{suffix}-66.png"


def _hero_card(player: pd.Series, rank: int = 1) -> str:
    """Render the big captain armband hero card as HTML."""
    code    = int(player.get("team_code", 1) or 1)
    is_gkp  = str(player.get("position", "")) == "GKP"
    shirt   = _shirt_url(code, is_gkp)
    fallback = f"{SHIRT_BASE}/shirt_1-66.png"
    name    = str(player.get("web_name", "?"))
    team    = str(player.get("team", ""))
    pos     = str(player.get("position", ""))
    price   = float(player.get("price", 0) or 0)
    form    = float(player.get("form", 0) or 0)
    ppg     = float(player.get("points_per_game", 0) or 0)
    own     = float(player.get("ownership", 0) or 0)
    xgi     = float(player.get("fpl_xgi_per90", 0) or 0)
    fdr     = float(player.get("next_gw_fdr", 3.0) or 3.0)
    pos_col = POS_COLORS.get(pos, "var(--ff-mint)")

    has_dgw = bool(player.get("has_dgw", False))
    dgw_badge = (
        '<span style="background:#f5c518;color:#000;border-radius:4px;'
        'padding:2px 6px;font-size:11px;font-weight:900;margin-left:8px;">2x DGW</span>'
        if has_dgw else ""
    )

    badges_html = render_badges(player, size="sm")
    avg_mins    = float(player.get("avg_minutes", 0) or 0)
    mins_str    = f"{avg_mins:.0f}" if avg_mins > 0 else "-"

    fdr_color = {1: theme.fill("mint"), 2: theme.fill("mint"), 3: theme.fill("orange"), 4: theme.fill("red"), 5: theme.fill("red")}.get(int(fdr), theme.fill("orange"))

    return f"""
    <div style="
        position:relative;
        background:linear-gradient(135deg, rgba(0,255,135,0.08) 0%, var(--ff-card) 100%);
        border:2px solid var(--ff-gold);
        border-radius:16px;
        padding:28px 32px;
        display:flex;
        align-items:center;
        gap:32px;
        max-width:580px;
        box-shadow:0 0 40px rgba(255,215,0,0.15);
        font-family:sans-serif;
    ">
      <!-- Armband stripe -->
      <div style="
          position:absolute; left:-2px; top:50%; transform:translateY(-50%);
          width:22px; height:70px;
          background:linear-gradient(180deg,var(--ff-gold),var(--ff-orange));
          border-radius:6px 0 0 6px;
          display:flex; align-items:center; justify-content:center;
      ">
        <span style="
            color:#000; font-weight:900; font-size:12px;
            writing-mode:vertical-rl; transform:rotate(180deg); letter-spacing:1px;
        ">C</span>
      </div>

      <!-- Shirt -->
      <div style="text-align:center; flex-shrink:0; padding-left:12px;">
        {face_html(player.get('code'), code, is_gkp, width=76)}
      </div>

      <!-- Info -->
      <div>
        <div style="font-size:26px; font-weight:900; color:var(--ff-text); margin-bottom:4px;">
          {name}{dgw_badge}
        </div>
        <div style="margin-bottom:8px;">{badges_html}</div>
        <div style="color:var(--ff-muted2); font-size:13px; margin-bottom:14px;">
          <span style="
              background:{pos_col}; color:#000; border-radius:3px;
              padding:1px 7px; font-weight:700; font-size:11px; margin-right:6px;
          ">{pos}</span>
          {team} &nbsp;·&nbsp; £{price:.1f}m &nbsp;·&nbsp; {own:.1f}% owned
        </div>
        <div style="display:flex; gap:24px;">
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:var(--ff-mint);">{form:.1f}</div>
            <div style="font-size:11px; color:var(--ff-muted2);">Form</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:var(--ff-mint);">{ppg:.1f}</div>
            <div style="font-size:11px; color:var(--ff-muted2);">PPG</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:{fdr_color};">{fdr:.0f}</div>
            <div style="font-size:11px; color:var(--ff-muted2);">Next FDR</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:var(--ff-cyan);">{xgi:.2f}</div>
            <div style="font-size:11px; color:var(--ff-muted2);">xGI/90</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:22px; font-weight:800; color:var(--ff-muted);">{mins_str}</div>
            <div style="font-size:11px; color:var(--ff-muted2);">Avg Mins</div>
          </div>
        </div>
      </div>
    </div>
    """


def _mini_card(player: pd.Series, rank: int) -> str:
    code    = int(player.get("team_code", 1) or 1)
    is_gkp  = str(player.get("position", "")) == "GKP"
    shirt   = _shirt_url(code, is_gkp)
    fallback = f"{SHIRT_BASE}/shirt_1-66.png"
    name    = str(player.get("web_name", "?"))
    team    = str(player.get("team", ""))
    form    = float(player.get("form", 0) or 0)
    ppg     = float(player.get("points_per_game", 0) or 0)
    fdr     = float(player.get("next_gw_fdr", 3.0) or 3.0)
    score   = float(player.get("captain_score", 0) or 0)
    own     = float(player.get("ownership", 0) or 0)
    pos     = str(player.get("position", ""))
    pos_col = POS_COLORS.get(pos, "#888")
    tcol    = team_color(player.get("team_short"))
    fdr_color = {1: theme.fill("mint"), 2: theme.fill("mint"), 3: theme.fill("orange"), 4: theme.fill("red"), 5: theme.fill("red")}.get(int(fdr), theme.fill("orange"))
    border_col = "var(--ff-gold)" if rank == 1 else "#silver" if rank == 2 else "var(--ff-line)"
    rank_labels = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4th", 5: "5th"}

    has_dgw = bool(player.get("has_dgw", False))
    dgw_tag = '<span style="background:#f5c518;color:#000;border-radius:3px;padding:1px 5px;font-size:10px;font-weight:900;margin-left:4px;">DGW</span>' if has_dgw else ""
    badges_html = render_badges(player, size="sm")

    return f"""
    <div style="
        background:var(--ff-row-alt);
        border:1px solid {border_col};
        border-left:3px solid {tcol};
        border-radius:12px;
        padding:14px 16px;
        display:flex;
        align-items:center;
        gap:14px;
        font-family:sans-serif;
        margin-bottom:8px;
    ">
      <div style="font-size:18px; width:28px; text-align:center; flex-shrink:0;">{rank_labels.get(rank, str(rank))}</div>
      {face_html(player.get('code'), code, is_gkp, width=40)}
      <div style="flex:1; min-width:0;">
        <div style="font-size:15px; font-weight:800; color:var(--ff-text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
          {name}{dgw_tag}
        </div>
        <div style="font-size:11px; color:var(--ff-muted2); margin-bottom:3px;">
          <span style="background:{pos_col};color:#000;border-radius:2px;padding:0 4px;font-weight:700;font-size:10px;margin-right:4px;">{pos}</span>
          {team} · {own:.1f}% owned
        </div>
        <div>{badges_html}</div>
      </div>
      <div style="display:flex; gap:16px; flex-shrink:0; text-align:center;">
        <div>
          <div style="font-size:16px; font-weight:800; color:var(--ff-mint);">{form:.1f}</div>
          <div style="font-size:10px; color:var(--ff-muted2);">Form</div>
        </div>
        <div>
          <div style="font-size:16px; font-weight:800; color:var(--ff-mint);">{ppg:.1f}</div>
          <div style="font-size:10px; color:var(--ff-muted2);">PPG</div>
        </div>
        <div>
          <div style="font-size:16px; font-weight:800; color:{fdr_color};">{fdr:.0f}</div>
          <div style="font-size:10px; color:var(--ff-muted2);">FDR</div>
        </div>
      </div>
      <div style="text-align:right; flex-shrink:0;">
        <div style="font-size:14px; font-weight:800; color:var(--ff-gold);">{score:.2f}</div>
        <div style="font-size:10px; color:var(--ff-muted2);">xP GW</div>
      </div>
    </div>
    """


def score_breakdown_chart(top5: pd.DataFrame, title: str, key: str) -> None:
    """Horizontal stacked bar showing captain score components for top 5."""
    from analytics.brain import POINT_PARTS
    components = [c for c, _ in POINT_PARTS]
    labels     = [l for _, l in POINT_PARTS]
    colors     = [theme.fill("muted2"), theme.fill("mint"), theme.fill("cyan"),
                  theme.fill("gold"), theme.fill("mag"), theme.fill("orange")]

    names = top5["web_name"].tolist()
    series = [
        (label, [round(float(v), 3) for v in top5[comp].fillna(0)], color)
        for comp, label, color in zip(components, labels, colors)
    ]
    opt = charts.stacked_bars_option(names, series, horizontal=True, title=title)
    from components.team_identity import player_photo_url as _ppu
    _code_by_name = dict(zip(players_df["web_name"], players_df.get("code")))
    charts.with_image_labels(opt, [_ppu(_code_by_name.get(n)) for n in names],
                             size=20)
    opt["grid"]["left"] = 122
    charts.render(opt, height="250px", key=key)


# ── Main layout ────────────────────────────────────────────────────────────────

from ui.page import header as _header
_header("Captain", "Who wears the armband this gameweek, ranked on the engine's expected points, with where those points come from.", kicker="This week", icon="military_tech")

with fpl_loader("Weighing up the armband", LINES_GENERIC):
    players_df, bootstrap = load_universe()

from data.fetchers.fpl_api import get_current_gameweek, fetch_fixtures
current_gw  = get_current_gameweek(bootstrap)
captain_gw  = get_next_gw(bootstrap)
fixtures_raw = fetch_fixtures()
fdr_map     = get_next_gw_fdr(bootstrap, fixtures_raw, captain_gw)


# ── Sidebar: team ID ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Your Squad")
    from config import FPL_TEAM_ID
    default_id = int(FPL_TEAM_ID) if FPL_TEAM_ID else 0
    team_id = st.number_input(
        "FPL Team ID",
        min_value=1,
        value=default_id,
        step=1,
        help="Enter your team ID to see captain picks from your own squad.",
    )
    st.caption("Leave blank / enter any ID to see all options.")
    diff_threshold = st.slider(
        "Differential threshold (max ownership %)",
        min_value=5, max_value=30, value=15, step=5,
        help="Differential captains: players owned by fewer than this % of managers.",
    )

# Score all players for captaincy.
# The ranking is the shared engine's expected points for this gameweek
# (analytics/brain via analytics/service), the same number Home, My Team and
# Claude use. The old weighted form/fixture score survives only as context
# columns on the cards. Three pages used to name three different captains.
scored = score_captains(players_df, fdr_map)
from analytics import brain as _brain, service as _svc
_long = _svc.projections(allow_compute=False)
if _long is None:
    _brain.warm_async(bootstrap, players_df, st.session_state.get("fixtures_df"))
    st.info("Projections are rebuilding after the last gameweek (a few minutes). "
            "Reload shortly · until then this page has nothing trustworthy to rank on.")
    st.stop()
_wk = _brain.point_parts(_long[_long["gw"] == int(captain_gw)])
_keep = ["code", "xp", "p60", "e_goals", "e_assists"] + [c for c, _ in _brain.POINT_PARTS]
scored = scored.merge(_wk[_keep], on="code", how="inner")
scored["captain_score"] = scored["xp"]
scored = scored[scored["status"].isin(["a", "d"])].copy()
scored = scored.sort_values("captain_score", ascending=False)

# ── Load squad if team_id provided ────────────────────────────────────────────
squad_df = None
if team_id and team_id > 0:
    try:
        with fpl_loader(f"Fetching squad {team_id}", LINES_SQUAD):
            squad_df = load_squad(team_id, current_gw)
    except Exception:
        st.sidebar.warning("Could not load squad. Showing global picks only.")

# ── Section 1: Your Squad Captain Pick ────────────────────────────────────────
if squad_df is not None:
    owned_ids = set(squad_df["fpl_id"].tolist())
    squad_scored = scored[scored["fpl_id"].isin(owned_ids)].head(5)

    # Merge team_code onto squad_scored for shirts
    if "team_code" not in squad_scored.columns:
        tc = players_df[["fpl_id", "team_code"]].drop_duplicates()
        squad_scored = squad_scored.merge(tc, on="fpl_id", how="left")

    _sec(f"Your captain · GW{captain_gw}",
         "Ranked on the engine's expected points. The goal and goal-or-assist chances are "
         "the ceiling: a captain is a bet on a haul, not just an average.")

    import math
    from components import ff_table as _T
    from components.team_identity import face_html as _face, player_photo_url as _ppu
    from ui.theme import var as _V
    pool = scored[scored["fpl_id"].isin(owned_ids)].head(8).copy()
    pool["p_goal"] = [1 - math.exp(-float(g)) for g in pool["e_goals"]]
    pool["p_ga"] = [1 - math.exp(-float(g) - float(a)) for g, a in zip(pool["e_goals"], pool["e_assists"])]
    if not pool.empty:
        top = pool.iloc[0]
        gap = float(top["xp"]) - float(pool.iloc[1]["xp"]) if len(pool) > 1 else 0.0
        from analytics import service as _svc3
        _fx = _svc3.fixtures_for(int(top["team_id"]), [int(captain_gw)])[0] if "team_id" in top else ""
        own = float(top.get("ownership") or 0)
        stance = ("Owned by %.0f%%: captaining him protects your rank more than it gains it." % own
                  if own >= 30 else
                  "Owned by %.0f%%: if he hauls, you gain on most of the field." % own)
        col_hero, col_chart = st.columns([1, 1])
        with col_hero:
            st.markdown("".join(x.strip() for x in f"""
<div class="ff-rise" style="padding:22px;border-radius:18px;background:{_V('card')};
  border:1px solid {_V('line')};border-top:3px solid {_V('gold')};">
  <div style="display:flex;gap:16px;align-items:center;">
    <div class="fplh-captain-pulse" style="width:80px;flex-shrink:0;border-radius:14px;">
      {_face(int(top['code']), int(top.get('team_code') or 1), top['position'] == 'GKP', 80)}</div>
    <div style="flex:1;min-width:0;">
      <div class="ff-display" style="font-size:30px;font-weight:900;color:{_V('text')};">{top['web_name']}</div>
      <div style="display:flex;gap:8px;align-items:baseline;">
        <span class="ff-display ff-num" style="font-size:34px;font-weight:900;color:{_V('gold')};">{float(top['xp']):.2f}</span>
        <span style="font-size:13px;color:{_V('muted')};">xP GW{captain_gw} · {_fx}</span></div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:14px;">
    <div style="padding:10px;border-radius:10px;background:{_V('row-alt')};"><div style="font-size:10.5px;
      letter-spacing:0.12em;color:{_V('muted2')};font-weight:700;">GOAL</div>
      <div class="ff-display ff-num" style="font-size:22px;font-weight:900;color:{_V('mint')};">{100 * top['p_goal']:.0f}%</div></div>
    <div style="padding:10px;border-radius:10px;background:{_V('row-alt')};"><div style="font-size:10.5px;
      letter-spacing:0.12em;color:{_V('muted2')};font-weight:700;">GOAL OR ASSIST</div>
      <div class="ff-display ff-num" style="font-size:22px;font-weight:900;color:{_V('cyan')};">{100 * top['p_ga']:.0f}%</div></div>
    <div style="padding:10px;border-radius:10px;background:{_V('row-alt')};"><div style="font-size:10.5px;
      letter-spacing:0.12em;color:{_V('muted2')};font-weight:700;">60+ MINUTES</div>
      <div class="ff-display ff-num" style="font-size:22px;font-weight:900;color:{_V('text')};">{100 * float(top['p60']):.0f}%</div></div>
  </div>
  <div style="font-size:13.5px;color:{_V('muted')};margin-top:12px;line-height:1.5;">
    {gap:.2f} xP clear of {pool.iloc[1]['web_name'] if len(pool) > 1 else '-'}{' · a coin flip' if gap < 0.3 else ''}. {stance}</div>
</div>""".splitlines()), unsafe_allow_html=True)
        with col_chart:
            if len(pool) > 1:
                score_breakdown_chart(pool.head(6), "Where the expected points come from",
                                      key="cap_breakdown_squad")

        _rows = [{"code": int(r["code"]), "web_name": r["web_name"],
                  "sub": "%s · %s" % (r.get("team_short", ""), r["position"]),
                  "fx": _svc3.fixtures_for(int(r["team_id"]), [int(captain_gw)])[0],
                  "xp": float(r["xp"]), "pg": 100 * r["p_goal"], "pga": 100 * r["p_ga"],
                  "p60": 100 * float(r["p60"]), "own": float(r.get("ownership") or 0)}
                 for _, r in pool.iterrows()]
        _T.render(_rows, [
            _T.col_face("code", url_fn=_ppu), _T.col_player("web_name", sub="sub"),
            _T.col_text("fx", "Fixture"),
            _T.col_bar("xp", "xP GW%d" % captain_gw, max_value=max(r["xp"] for r in _rows), fmt="%.2f"),
            _T.col_num("pg", "Goal %", fmt="%.0f"), _T.col_num("pga", "G or A %", fmt="%.0f"),
            _T.col_num("p60", "60+ min %", fmt="%.0f"), _T.col_num("own", "Owned %", fmt="%.1f"),
        ], key="cap_shortlist", max_height=420)

    st.markdown("---")

# ── Section 2: Differential captains ──────────────────────────────────────────
# A differential captain is a rank bet: owned by few, so a haul moves you past
# most of the field. Shown for anyone, owned or not, from the same engine.
import math as _m
from analytics import service as _svc4
from components import ff_table as _T2
from components.team_identity import player_photo_url as _ppu2
_sec(f"Differential captains · GW{captain_gw}",
     f"Owned by fewer than {diff_threshold}% of managers. If one of these hauls, you gain on "
     f"almost everyone. Sorted by expected points.")
diffs = scored[scored["ownership"].fillna(0) <= diff_threshold].head(8).copy()
if not diffs.empty:
    _drows = [{"code": int(r["code"]), "web_name": r["web_name"],
               "sub": "%s · %s" % (r.get("team_short", ""), r["position"]),
               "fx": _svc4.fixtures_for(int(r["team_id"]), [int(captain_gw)])[0],
               "xp": float(r["xp"]),
               "pg": 100 * (1 - _m.exp(-float(r["e_goals"]))),
               "pga": 100 * (1 - _m.exp(-float(r["e_goals"]) - float(r["e_assists"]))),
               "own": float(r.get("ownership") or 0)} for _, r in diffs.iterrows()]
    _T2.render(_drows, [
        _T2.col_face("code", url_fn=_ppu2), _T2.col_player("web_name", sub="sub"),
        _T2.col_text("fx", "Fixture"),
        _T2.col_bar("xp", "xP GW%d" % captain_gw, max_value=max(r["xp"] for r in _drows), fmt="%.2f"),
        _T2.col_num("pg", "Goal %", fmt="%.0f"), _T2.col_num("pga", "G or A %", fmt="%.0f"),
        _T2.col_num("own", "Owned %", fmt="%.1f"),
    ], key="cap_diffs", max_height=420)
else:
    st.info(f"No differential captains under {diff_threshold}% ownership with a fixture this week.")


# (Player lookups live in the rail's search on every page; no per-page copy.)
