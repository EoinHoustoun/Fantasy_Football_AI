"""Helper for research_fpred_team_rates.py · runs inside F Pred's interpreter.

argv: jobs.parquet (fold, cutoff, home, away) -> rates.parquet with each
fixture's Dixon-Coles lambdas and clean-sheet probabilities from the score
matrix, the model refitted per fold on matches dated before the cutoff.
cwd must be the F_PRED repo.
"""
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from data import load_data  # noqa: E402  (F Pred's data.py)
from models import compute_dixon_coles_ratings, predict_dixon_coles  # noqa: E402

jobs = pd.read_parquet(sys.argv[1])
df = load_data()
df["Date"] = pd.to_datetime(df["Date"])
teams = set(df["HomeTeam"]) | set(df["AwayTeam"])
unknown = sorted((set(jobs["home"]) | set(jobs["away"])) - teams)
print("names unknown to F Pred:", unknown, flush=True)
out = []
for fold, g in jobs.groupby("fold"):
    t0 = time.time()
    r = compute_dixon_coles_ratings(df[df["Date"] < pd.Timestamp(g["cutoff"].iloc[0])])
    for _, j in g.iterrows():
        if j["home"] not in r["attacks"] or j["away"] not in r["attacks"]:
            continue
        p = predict_dixon_coles(j["home"], j["away"], r)
        m = np.asarray(p["score_matrix"])
        out.append({"fold": fold, "home": j["home"], "away": j["away"],
                    "lam_h": float(p["lambda_home"]), "lam_a": float(p["lambda_away"]),
                    "cs_h": float(m[:, 0].sum()), "cs_a": float(m[0, :].sum())})
    print("dc fold %d: %.1fs" % (fold, time.time() - t0), flush=True)
pd.DataFrame(out).to_parquet(sys.argv[2])
