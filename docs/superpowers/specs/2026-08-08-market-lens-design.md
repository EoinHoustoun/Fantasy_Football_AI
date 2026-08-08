# Market Lens · bookmaker player props as an independent second opinion

Design doc · 2026-08-08 · branch `draft-page-hardening`

**Status: PARKED.** Blocked on the user creating a Betfair delayed app key, which
needs an interactive browser login to the Accounts API Demo Tool. Nothing here is
built. Written up so the research is not repeated.

## Why this was considered

Every projection in the app is derived from the same family of inputs: last
season's returns, fixture ease, and three models that all read broadly the same
history. `analytics/consensus.py` blends ours, Scout and Hub, but a blend of
three correlated models is not the same as an independent check.

Bookmaker markets are genuinely independent, priced by people with money at risk,
and they update through the week as team news lands.

## What was rejected, and why

**MCP servers.** The user asked about `rishijatia/fantasy-pl-mcp` and
`nguyenanhducs/fpl-mcp-server`. Both were rejected:

1. An MCP server is a tool for the agent, not for the app. Streamlit pages call
   Python functions, not MCP servers. Adding one would run a second process to
   proxy HTTP requests the app already makes.
2. Both wrap only `fantasy.premierleague.com/api`. The app already wraps that,
   plus vaastav, the pre-wipe 2025-26 archive, FBref, Understat,
   football-data.co.uk, Fantasy Football Hub, and Dixon-Coles.
3. Their added value (`suggest_captain`, fixture difficulty) is a downgrade on
   the xP engine, consensus blend and squad MILP already in the repo.
4. `rishijatia` additionally requires extracting OIDC refresh tokens from browser
   local storage, to reach `get_my_team`, which the app already gets from a team
   ID with no auth at all.

**Buying clean-sheet odds.** Not needed. `data/fetchers/dixon_coles.py` already
fits attack and defence ratings with a 16-week decay, and clean-sheet probability
falls out of it. What cannot be derived from Dixon-Coles is the player-level
split: which of a team's expected goals land on which player, and who takes
penalties. That is the only part worth paying for.

## Source decision

Betfair Exchange with the **free delayed app key**, snapshotting forward from
GW1 rather than buying history.

| | Betfair delayed | The Odds API Business |
|---|---|---|
| Cost | £0 | $99/mo |
| Margin to strip | none, exchange prices | bookmaker overround |
| Historical odds | none | included |
| Setup | Betfair account + app key | API key |
| Known gap | no `totalMatched` volume | credits burn as markets × regions |

The delay is 1 to 180 seconds, which is irrelevant against a Friday FPL deadline.
The missing `totalMatched` matters more: without traded volume there is no direct
liquidity measure, so **back/lay spread width** stands in as the confidence
signal.

The history gap closes on its own. Snapshotting from GW1 gives six weeks of
paired odds-and-outcome data by GW6, which is the walk-forward evidence needed to
decide whether this signal ever deserves a place in the blend.

## The insight that shapes the design

[Betfair's football rules](https://support.betfair.com/app/answers/detail/exchange-football-soccer-rules/)
void anytime-scorer bets on players who never take the pitch. So the price is
**P(scores | plays)**, not P(scores).

That composes cleanly with what the app already has, rather than competing:

```
P(scores) = P(plays)              ×  P(scores | plays)
             ours, ffh_nailedness    market, sharper than us
```

The market answers the question our model is worst at, and stays silent on the
one `ffh_nailedness` already answers well.

## Design

### Markets pulled, per fixture

| Market | Used for | Why |
|---|---|---|
| `ANYTIME_GOALSCORER` | per-player P(scores \| plays) | only source of player-level goal share |
| `CORRECT_SCORE` | clean sheets as Σ P(opponent scores 0) | better traded than a dedicated clean-sheet market, and yields the full joint distribution |
| `MATCH_ODDS` | liquidity anchor and sanity check | deepest market on the exchange |

Probability is the back/lay midpoint. No overround stripping, because an exchange
has no bookmaker margin. Spread width is recorded as the confidence measure.

### Comparison is per component, never a single headline

A single "market xP" number would be dishonest. The market prices goals and clean
sheets and says nothing about assists, bonus or saves, so comparing it to a
complete xP manufactures disagreement that is not there.

Both sides get decomposed and only the comparable components are compared:

```
                  Ours    Market    Δ
Goals             2.8      1.6    -1.2   comparable
Clean sheet       0.4      0.5    +0.1   comparable
Assists           1.1       --           ours only, greyed
Bonus             0.9       --
Appearance        2.0      2.0
```

Goal points convert by Poisson inversion, `λ = -ln(1 - p)`, then
`λ × position_points` (6 DEF, 5 MID, 4 FWD). One documented, unit-tested function.

### Modules

```
data/fetchers/betfair.py     auth, session cache, the three market pulls
analytics/market_lens.py     prices → probabilities → points components
scripts/snapshot_odds.py     cron entry, writes parquet
views/20_market.py           the page
```

Nothing in `consensus.py`, `xp_engine.py` or any live page is touched. Deleting
four files removes the feature completely.

### Snapshot cadence

Three captures per gameweek: deadline minus 72h, 24h and 2h. Append-only to
`data/cache/odds/`, never overwritten, same doctrine as `data/cache/archive/`.

The **drift between captures** is itself a signal. A scorer price moving 2.10 to
2.75 on a Friday afternoon is the market reacting to a press conference before it
reaches the injury feeds. That may justify the build regardless of whether the
level ever beats our projection.

### Name matching, which is the part that will break

Betfair runner names against FPL codes is the same failure class as the bug that
silently dropped second opinions. It must fail loud:

- every snapshot records a match rate and the unmatched runners
- below a floor (start at 90%, a guess with no evidence yet) the snapshot is
  written but flagged `degraded`
- the page renders a warning banner instead of implying full coverage
- a test asserts a deliberately unmatchable runner appears in the unmatched list
  rather than vanishing

### Credentials

This repo is public. The user sets `BETFAIR_USERNAME`, `BETFAIR_PASSWORD` and
`BETFAIR_APP_KEY` in the environment themselves. Session token cached at
`~/.fpl/betfair_session` with mode 0600. That path and `data/cache/odds/` go into
`.gitignore` before the first line of the fetcher is written.

### Tests

Offline against recorded fixtures, no network in CI: Poisson inversion, back/lay
midpoint, clean-sheet derivation from correct score, name-match coverage floor,
degraded-snapshot rendering, and empty-market handling for fixtures whose
goalscorer market has not opened yet.

## Open questions when this is picked up

1. Is 90% the right coverage floor? Picked with no evidence.
2. Does the anytime-goalscorer market carry usable liquidity for mid-price
   players, or only for premiums? Unknown until the first snapshot.
3. How early do Betfair goalscorer markets open relative to the FPL deadline?
