"""Dempster-Shafer evidence fusion.

Combines mass functions from the three PRISM domains (prognosis, compliance,
rehabilitation) over the frame of discernment {On-Track, At-Risk, Critical} into
a single recovery-trajectory index, using the exact orthogonal-sum (Dempster's
rule) with explicit conflict normalization.
"""
import numpy as np
from itertools import product
from . import config as C

FRAME = C.DS_FRAME
# focal elements: the three singletons plus the full-frame "uncertainty" set
FOCALS = [("On-Track",), ("At-Risk",), ("Critical",), tuple(FRAME)]


def combine_two(m1, m2):
    """Dempster's rule of combination for two mass functions (dicts over FOCALS)."""
    comb, conflict = {}, 0.0
    for a, b in product(m1, m2):
        inter = tuple(x for x in a if x in set(b))
        mass = m1[a] * m2[b]
        if inter:
            comb[inter] = comb.get(inter, 0.0) + mass
        else:
            conflict += mass
    if conflict >= 1.0:
        raise ValueError("total conflict; sources fully contradictory")
    return {k: v / (1.0 - conflict) for k, v in comb.items()}, conflict


def fuse(masses):
    """Combine a list of mass functions; returns (fused_mass, pignistic_probs)."""
    m = masses[0]
    for nxt in masses[1:]:
        m, _ = combine_two(m, nxt)
    # pignistic transform for a point recovery-index distribution
    bet = {f: 0.0 for f in FRAME}
    for focal, mass in m.items():
        for f in focal:
            bet[f] += mass / len(focal)
    return m, bet


def domain_mass(on_track, at_risk, critical, uncertainty):
    s = on_track + at_risk + critical + uncertainty
    return {("On-Track",): on_track / s, ("At-Risk",): at_risk / s,
            ("Critical",): critical / s, tuple(FRAME): uncertainty / s}


def demo(seed=C.MASTER_SEED):
    """Illustrative fusion of one claim's three domain opinions."""
    rng = np.random.default_rng(seed)
    prognosis = domain_mass(0.55, 0.25, 0.08, 0.12)
    compliance = domain_mass(0.40, 0.35, 0.15, 0.10)
    rehab = domain_mass(0.60, 0.22, 0.08, 0.10)
    fused, bet = fuse([prognosis, compliance, rehab])
    return dict(pignistic={k: round(v, 3) for k, v in bet.items()},
                index=max(bet, key=bet.get))
