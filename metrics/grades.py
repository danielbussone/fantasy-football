"""Role / Boom / GBFL-PAR grades from window features plus frozen weights.

Models are small ridge regressions on z-scored features, solved in pure
Python (no numpy in the app's venv). A missing feature is imputed at the
training mean (z = 0). Weights are fit by backtest_metrics.py on 2023–24
and frozen in metrics/weights.json.

PAR is points above the best free agent: (predicted pts/game − replacement
pts/game) × weeks left, where replacement is the (N+1)th best predicted
player at the position and N = 10 teams × that position's roster cap.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import correlation, fmean, pstdev

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_PATH = ROOT / "metrics" / "weights.json"
TEAMS = 10
# lineup/start_sit.py ROSTER_CAPS: 2 QB · 5 RB · 6 WR · 2 TE · 2 K · 2 DST.
ROSTER_CAP = {"QB": 2, "RB": 5, "WR": 6, "TE": 2, "K": 2, "DST": 2}
LAST_WEEK = 18


def replacement_rank(pos: str) -> int:
    return TEAMS * ROSTER_CAP.get(pos, 2)


@dataclass
class Model:
    feats: list[str]
    means: list[float]
    sds: list[float]
    coefs: list[float] = field(default_factory=list)  # intercept first

    def z(self, row: dict) -> list[float]:
        out = []
        for f, m, s in zip(self.feats, self.means, self.sds):
            v = row.get(f)
            out.append(0.0 if v is None or s <= 0 else (float(v) - m) / s)
        return out

    def predict(self, row: dict) -> float:
        x = self.z(row)
        return self.coefs[0] + sum(c * v for c, v in zip(self.coefs[1:], x))

    def to_dict(self) -> dict:
        return {"feats": self.feats, "means": self.means, "sds": self.sds, "coefs": self.coefs}

    @classmethod
    def from_dict(cls, d: dict) -> "Model":
        return cls(list(d["feats"]), list(d["means"]), list(d["sds"]), list(d["coefs"]))


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("singular system")
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r == col:
                continue
            k = m[r][col] / m[col][col]
            if k:
                for c in range(col, n + 1):
                    m[r][c] -= k * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit(rows: list[dict], feats: list[str], target: str, lam: float = 1.0) -> Model:
    """Ridge fit of `target` on z-scored `feats`; the intercept isn't penalized."""
    means, sds = [], []
    for f in feats:
        vals = [float(r[f]) for r in rows if r.get(f) is not None]
        means.append(fmean(vals) if vals else 0.0)
        sds.append(pstdev(vals) if len(vals) > 1 else 0.0)
    model = Model(list(feats), means, sds)
    xs = [[1.0] + model.z(r) for r in rows]
    ys = [float(r[target]) for r in rows]
    k = len(feats) + 1
    xtx = [[sum(x[i] * x[j] for x in xs) for j in range(k)] for i in range(k)]
    for i in range(1, k):
        xtx[i][i] += lam
    xty = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(k)]
    model.coefs = _solve(xtx, xty)
    return model


def fit_blend(rows: list[dict], feats: list[str], weights: list[float], target: str) -> Model:
    """A fixed blend of z-scored features (e.g. 40% pts/g + 60% WOPR), scaled to
    `target` units by a one-variable least-squares fit so it predicts pts/game."""
    base = fit(rows, feats, target, lam=0.0)  # only for the feature means/sds
    probe = Model(base.feats, base.means, base.sds, [0.0, *weights])
    xs = [probe.predict(r) for r in rows]
    ys = [float(r[target]) for r in rows]
    mx, my = fmean(xs), fmean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx > 0 else 0.0
    return Model(base.feats, base.means, base.sds, [my - slope * mx, *(slope * w for w in weights)])


def r2(y: list[float], yhat: list[float]) -> float:
    my = fmean(y)
    ss_tot = sum((v - my) ** 2 for v in y)
    ss_res = sum((v - p) ** 2 for v, p in zip(y, yhat))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def spearman(a: list[float], b: list[float]) -> float:
    if len(a) < 3 or pstdev(a) == 0 or pstdev(b) == 0:
        return 0.0
    return correlation(a, b, method="ranked")


def pearson(a: list[float], b: list[float]) -> float:
    if len(a) < 3 or pstdev(a) == 0 or pstdev(b) == 0:
        return 0.0
    return correlation(a, b)


def replacement_value(preds: list[float], pos: str) -> float:
    """Predicted pts/game of the best free agent: the (N+1)th best at the position,
    N = teams × roster cap; the worst player when the pool is shorter than that."""
    ranked = sorted(preds, reverse=True)
    n = replacement_rank(pos)
    return ranked[n] if len(ranked) > n else (ranked[-1] if ranked else 0.0)


def par(pred_ppg: dict[str, float], pos: str, week: int, games: dict[str, float] | None = None) -> dict[str, float]:
    """{player: points above the best free agent over the rest of the season}.

    `games` is each player's expected games left (metrics.availability.expected_games);
    anyone missing from it gets every week left.
    """
    repl = replacement_value(list(pred_ppg.values()), pos)
    weeks_left = max(0, LAST_WEEK - int(week))
    g = games or {}
    return {p: (v - repl) * g.get(p, weeks_left) for p, v in pred_ppg.items()}


def percentile_grade(values: dict[str, float]) -> dict[str, int]:
    """0–100 percentile within the given pool (ties share the lower rank)."""
    ordered = sorted(values.values())
    n = len(ordered)
    if n <= 1:
        return {k: 50 for k in values}
    out = {}
    for k, v in values.items():
        below = sum(1 for x in ordered if x < v)
        out[k] = round(100 * below / (n - 1))
    return out


def save_weights(payload: dict, path: Path = WEIGHTS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_weights(path: Path = WEIGHTS_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
