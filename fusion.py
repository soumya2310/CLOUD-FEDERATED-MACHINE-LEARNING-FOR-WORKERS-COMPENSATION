"""Dempster-Shafer evidence fusion over the frame
Theta = {On-Track (O), At-Risk (A), Critical (C)}.

Three per-claim signals (prognosis risk, compliance normality, rehab stage)
become basic probability assignments (BPAs); Dempster's rule combines them and
the pignistic transform yields the recovery-trajectory index H = BetP({O}).
Includes a conflict-mass safeguard (Dubois-Prade style discounting).
"""
import itertools
import numpy as np

FRAME = ["O", "A", "C"]
SUBSETS = [frozenset(s) for r in range(1, 4)
           for s in itertools.combinations(FRAME, r)]
FULL = frozenset(FRAME)


def _bpa_from_signal(kind, v, disc=0.8):
    """Build a BPA dict for one evidence source. v in [0,1]."""
    m = {s: 0.0 for s in SUBSETS}
    if kind == "prognosis":       # high v = high risk
        m[frozenset(["C"])] = disc * v
        m[frozenset(["O"])] = disc * (1 - v)
    elif kind == "compliance":    # high v = normal
        m[frozenset(["O"])] = disc * v
        m[frozenset(["A"])] = disc * (1 - v)
    else:                         # rehab stage: high v = good function
        m[frozenset(["O"])] = disc * v
        m[frozenset(["C"])] = disc * (1 - v)
    m[FULL] += 1.0 - sum(m.values())
    return m


def _combine(m1, m2):
    """Dempster's rule of combination for two BPAs; returns (m, conflict K)."""
    out = {s: 0.0 for s in SUBSETS}
    K = 0.0
    for a, va in m1.items():
        if va == 0:
            continue
        for b, vb in m2.items():
            if vb == 0:
                continue
            inter = a & b
            if not inter:
                K += va * vb
            else:
                out[frozenset(inter)] += va * vb
    if K >= 1 - 1e-9:
        return m2, 1.0
    for s in out:
        out[s] /= (1 - K)
    return out, K


def _pignistic(m):
    betp = {e: 0.0 for e in FRAME}
    for s, v in m.items():
        if v == 0:
            continue
        for e in s:
            betp[e] += v / len(s)
    return betp


def recovery_index(prognosis_risk, compliance_normality, rehab_stage,
                   k_max=0.6, disc=0.8):
    """Vectorized H for arrays of per-claim signals. Returns H in [0,1] and the
    mean conflict mass (for reporting the safeguard trigger rate)."""
    n = len(prognosis_risk)
    H = np.empty(n)
    conflicts = np.empty(n)
    for i in range(n):
        m1 = _bpa_from_signal("prognosis", float(prognosis_risk[i]), disc)
        m2 = _bpa_from_signal("compliance", float(compliance_normality[i]), disc)
        m3 = _bpa_from_signal("rehab", float(rehab_stage[i]), disc)
        m12, k12 = _combine(m1, m2)
        # safeguard: discount before final combine if conflict already high
        if k12 > k_max:
            for s in m12:
                m12[s] *= 0.85
            m12[FULL] += 1 - sum(m12.values())
        m123, k123 = _combine(m12, m3)
        conflicts[i] = max(k12, k123)
        H[i] = _pignistic(m123)["O"]
    return H, float(conflicts.mean())
