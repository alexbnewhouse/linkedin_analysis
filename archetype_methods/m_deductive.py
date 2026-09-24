"""Deductive methods: start from the framework (the literature prior) and
project it onto the data.

D1  lexicon + SOC crosswalk     exact / longest-substring match against the
                                framework's 390 representative titles, then
                                a head-noun lexicon derived from those titles,
                                then a hand-written SOC major/detail -> archetype
                                crosswalk. Fully explainable, no learning.
D2  seed nearest-neighbor       embed the 390 seed titles; a role takes the
                                cosine-weighted vote of its 5 nearest seeds,
                                abstaining below a cosine floor.
D2p prototype cosine            nearest of ten prototype paragraphs
                                (orientation + skills + roles, plus a 'none').
D3  LLM zero-shot               the framework text as the prompt, a local
                                model as the classifier (run via bench_llm.py,
                                gold only; see EVALUATION.md for cost).
D4  O*NET bridge                classify the 1,016 O*NET occupations by their
                                official descriptions (D2p + D2 ensemble), then
                                let roles inherit through their SOC code.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict

import numpy as np
import pyarrow as pa

from . import common as C
from . import framework as F

NONE = F.NONE_KEY

# ---------------------------------------------------------------- D1
# SOC major -> archetype. A deductive prior: what the framework would say about
# each O*NET major group. 'none' = outside all nine orientations.
SOC_MAJOR_MAP = {
    "11": "leaders", "13": "analysts", "15": "builders", "17": "builders",
    "19": "researchers", "21": "helpers", "23": "advocates", "25": "researchers",
    "27": "communicators", "29": NONE, "31": NONE, "33": NONE, "35": "helpers",
    "37": NONE, "39": "helpers", "41": "connectors", "43": "leaders", "45": NONE,
    "47": NONE, "49": NONE, "51": NONE, "53": NONE, "55": NONE,
}
# Detailed overrides where the major is heterogeneous.
SOC_DETAIL_MAP = {
    "11-2011": "communicators", "11-2021": "communicators", "11-2022": "connectors",
    "11-2032": "communicators", "11-3031": "stewards", "11-3021": "builders",
    "11-3121": "leaders", "11-9031": "leaders", "11-9032": "leaders", "11-9033": "leaders",
    "11-9111": NONE, "11-9141": "leaders", "11-9151": "helpers",
    "13-1071": "connectors", "13-1075": "advocates", "13-1111": "analysts",
    "13-1121": "leaders", "13-1141": "stewards", "13-1151": "researchers",
    "13-1161": "communicators", "13-1023": "stewards", "13-1041": "advocates",
    "13-1051": "stewards", "13-2011": "stewards", "13-2041": "stewards",
    "13-2051": "stewards", "13-2052": "stewards", "13-2053": "stewards",
    "13-2054": "stewards", "13-2061": "stewards", "13-2072": "stewards",
    "13-2081": "stewards", "13-2082": "stewards", "13-2099": "stewards",
    "15-1211": "analysts", "15-2041": "analysts", "15-2051": "analysts",
    "27-3011": "communicators", "27-3091": "communicators",
    "41-1011": "helpers", "41-2011": "helpers", "41-2021": "helpers",
    "41-2022": "helpers", "41-2031": "helpers", "41-9011": "communicators",
    "43-3011": "stewards", "43-3021": "stewards", "43-3031": "stewards",
    "43-3051": "stewards", "43-3061": "stewards", "43-4051": "helpers",
    "43-4081": "helpers", "43-4171": "helpers", "43-1011": "leaders",
    "43-9081": "communicators",
    "21-2011": "helpers", "25-4011": "researchers", "25-4012": "researchers",
    "25-4022": "researchers", "25-4031": "researchers",
    "29-1141": NONE, "29-1229": NONE, "29-9021": "analysts", "29-2072": "stewards",
    "33-1021": NONE, "39-9031": "helpers", "39-9032": "helpers", "39-9041": "helpers",
}

_WORD = re.compile(r"[a-z0-9]+")

# The framework's own boundary, enumerated so seed-based methods can say 'none'.
# These are not the director's words; they spell out "outside all nine
# orientations" (trades, production, transport, clinical practice, uniformed
# service, placeholders). Kept short and generic on purpose.
NONE_SEEDS = (
    "Registered Nurse", "Nurse", "Physician", "Pharmacist", "Pharmacy Technician",
    "Medical Assistant", "Dental Hygienist", "Physical Therapist", "Laboratory Technician",
    "Surgeon", "Veterinarian", "Paramedic", "Radiologic Technologist",
    "Electrician", "Plumber", "Carpenter", "Welder", "Mechanic", "Machinist", "Technician",
    "Maintenance Technician", "HVAC Technician", "Construction Worker", "Foreman",
    "Production Worker", "Assembler", "Machine Operator", "Forklift Operator",
    "Truck Driver", "Delivery Driver", "Warehouse Associate", "Material Handler", "Mover",
    "Police Officer", "Firefighter", "Security Officer", "Correctional Officer", "Soldier",
    "Sergeant", "Military Police", "Pilot", "Flight Attendant",
    "Farm Worker", "Landscaper", "Janitor", "Housekeeper", "Cook", "Line Cook", "Dishwasher",
    "Athlete", "Owner", "Founder", "Co-Founder", "Self-Employed", "Independent Contractor",
    "Freelancer", "Retired", "Unemployed", "Student", "Intern", "Volunteer", "Member",
    "Board Member", "Committee Member",
)


def norm(s: str) -> str:
    return " ".join(_WORD.findall((s or "").lower().replace("&", " and ")))


def _seed_index():
    """title -> Counter(archetype). Ambiguous seeds keep both keys."""
    idx: dict[str, Counter] = defaultdict(Counter)
    for title, key, _ in F.seeds():
        idx[norm(title)][key] += 1
    for title in NONE_SEEDS:
        idx[norm(title)][NONE] += 1
    return idx


def _head_noun_lexicon(seed_idx) -> dict[str, str]:
    """Last token of a seed title -> archetype, kept only when >= 80% agree."""
    c: dict[str, Counter] = defaultdict(Counter)
    for title, keys in seed_idx.items():
        last = title.split()[-1]
        for k, n in keys.items():
            c[last][k] += n
    out = {}
    for tok, cnt in c.items():
        k, n = cnt.most_common(1)[0]
        if n / sum(cnt.values()) >= 0.8 and tok not in {"manager", "director", "specialist",
                                                        "coordinator", "associate", "assistant",
                                                        "analyst", "officer", "consultant",
                                                        "lead", "chair", "member"}:
            out[tok] = k
    return out


def d1(t: pa.Table) -> tuple[dict, Counter]:
    seed_idx = _seed_index()
    seeds_sorted = sorted(seed_idx, key=len, reverse=True)
    lex = _head_noun_lexicon(seed_idx)
    out, methods = {}, Counter()
    displays = t["role_display"].to_pylist()
    raws = t["role_text"].to_pylist()
    socd = t["soc_detail"].to_pylist()
    socs = t["soc_detail_support"].to_pylist()
    socm = t["soc_major"].to_pylist()
    owner = t["owner_share"].to_pylist()
    for rc, disp, raw, sd, ss, sm, ow in zip(t["role_canonical"].to_pylist(), displays, raws,
                                             socd, socs, socm, owner):
        text = norm(disp)
        label, method, score = None, None, 0.0
        if (ow or 0) >= 0.9 and len(text.split()) <= 2 and any(
                w in text for w in ("owner", "founder", "self", "freelance", "contractor", "entrepreneur")):
            label, method, score = NONE, "placeholder", 1.0
        if label is None and text in seed_idx:
            keys = seed_idx[text]
            if len(keys) == 1:
                label, method, score = next(iter(keys)), "seed_exact", 1.0
        if label is None:
            padded = f" {text} "
            for s in seeds_sorted:
                if " " in s and f" {s} " in padded and len(seed_idx[s]) == 1:
                    label, method, score = next(iter(seed_idx[s])), "seed_substring", 0.8
                    break
        if label is None and text:
            last = text.split()[-1]
            if last in lex:
                label, method, score = lex[last], "head_noun", 0.6
        if label is None and sd and (ss or 0) >= 3:
            if sd in SOC_DETAIL_MAP:
                label, method, score = SOC_DETAIL_MAP[sd], "soc_detail", 0.5
            elif sd[:2] in SOC_MAJOR_MAP:
                label, method, score = SOC_MAJOR_MAP[sd[:2]], "soc_detail_major", 0.4
        if label is None and sm in SOC_MAJOR_MAP:
            label, method, score = SOC_MAJOR_MAP[sm], "soc_major", 0.3
        if label is None:
            label, method = "abstain", "abstain"
        out[rc] = (label, score)
        methods[method] += 1
    return out, methods


# ---------------------------------------------------------------- D2 / D2p
def seed_matrix():
    titles, keys = [], []
    for title, key, _ in F.seeds():
        titles.append(title); keys.append(key)
    for title in NONE_SEEDS:
        titles.append(title); keys.append(NONE)
    V = C.encode([x.lower() for x in titles], "seed_titles")
    return titles, keys, V


def d2(t: pa.Table, X: np.ndarray, k: int = 5, floor: float = 0.0) -> dict:
    """Cosine-weighted vote of the k nearest seed titles; score = top cosine."""
    _, keys, V = seed_matrix()
    keys = np.asarray(keys)
    S = X @ V.T
    top = np.argpartition(-S, k, axis=1)[:, :k]
    out = {}
    for i, rc in enumerate(t["role_canonical"].to_pylist()):
        votes = Counter()
        for j in top[i]:
            votes[keys[j]] += max(S[i, j], 0.0)
        label, _ = votes.most_common(1)[0]
        best = float(S[i, top[i]].max())
        out[rc] = (label if best >= floor else "abstain", best)
    return out


def prototype_matrix():
    texts = [F.prototype_text(a) for a in F.ARCHETYPES]
    keys = list(F.KEYS)
    texts.append("Work outside these orientations. Skilled trades, construction, installation and "
                 "repair, manufacturing and production, transportation and material moving, farming, "
                 "clinical healthcare practice such as nurse, physician, pharmacist, technician, "
                 "protective and uniformed service, military, athletes, and placeholder entries "
                 "such as owner, founder, self-employed, retired, student, unemployed.")
    keys.append(NONE)
    return keys, C.encode(texts, "prototypes")


def d2p(t: pa.Table, X: np.ndarray, floor: float = 0.0) -> dict:
    keys, P = prototype_matrix()
    S = X @ P.T
    out = {}
    for i, rc in enumerate(t["role_canonical"].to_pylist()):
        j = int(S[i].argmax())
        out[rc] = (keys[j] if S[i, j] >= floor else "abstain", float(S[i, j]))
    return out


# ---------------------------------------------------------------- D4
def onet_map() -> dict[str, tuple[str, float]]:
    """O*NET-SOC code -> (archetype, score) from the official description."""
    codes, texts = [], []
    with C.ONET_OCC.open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            code, title, desc = line.rstrip("\n").split("\t", 2)
            codes.append(code[:7]); texts.append(f"{title}. {desc}")
    X = C.encode(texts, "onet_descriptions")
    keys, P = prototype_matrix()
    _, skeys, V = seed_matrix()
    skeys = np.asarray(skeys)
    Sp = X @ P.T
    Ss = X @ V.T
    out = {}
    for i, code in enumerate(codes):
        if code in out:            # keep the base occupation (.00) over specialties
            continue
        votes = Counter({k: 0.0 for k in keys})
        for j, k in enumerate(keys):
            votes[k] += Sp[i, j]
        top = np.argpartition(-Ss[i], 5)[:5]
        for j in top:
            votes[skeys[j]] += Ss[i, j] / 5
        label, sc = votes.most_common(1)[0]
        out[code] = (label, float(sc))
    return out


def d4(t: pa.Table) -> tuple[dict, dict]:
    om = onet_map()
    # a data-derived major-group prior: majority of the mapped detail codes
    maj: dict[str, Counter] = defaultdict(Counter)
    for code, (lab, _) in om.items():
        maj[code[:2]][lab] += 1
    major_map = {m: c.most_common(1)[0][0] for m, c in maj.items()}
    out = {}
    for rc, sd, ss, sm in zip(t["role_canonical"].to_pylist(), t["soc_detail"].to_pylist(),
                              t["soc_detail_support"].to_pylist(), t["soc_major"].to_pylist()):
        if sd and (ss or 0) >= 3 and sd in om:
            out[rc] = om[sd]
        elif sm in major_map:
            out[rc] = (major_map[sm], 0.3)
        else:
            out[rc] = ("abstain", 0.0)
    return out, {"onet_codes": len(om), "major_map": major_map}


def run():
    from . import metrics as M
    t = C.load_roles()
    X = C.encode([x or "" for x in t["role_text"].to_pylist()], "role_text")
    results, assignments = {}, {}
    a, methods = d1(t)
    assignments["D1_lexicon_soc"] = a
    results["D1_lexicon_soc"] = M.score(a, name="D1_lexicon_soc") | {"layer_mix": dict(methods)}
    for floor in (0.0, 0.75, 0.80, 0.85):
        a = d2(t, X, floor=floor)
        nm = f"D2_seed_knn_f{floor:.2f}"
        assignments[nm] = a
        results[nm] = M.score(a, name=nm)
    for floor in (0.0, 0.55):
        a = d2p(t, X, floor=floor)
        nm = f"D2p_prototype_f{floor:.2f}"
        assignments[nm] = a
        results[nm] = M.score(a, name=nm)
    a, info = d4(t)
    assignments["D4_onet_bridge"] = a
    results["D4_onet_bridge"] = M.score(a, name="D4_onet_bridge") | info
    for nm, s in results.items():
        print(f"{nm}: cov={s['coverage']:.2f} strict={s['acc_strict']:.3f} lenient={s['acc_lenient']:.3f} "
              f"assigned={s['acc_strict_assigned']:.3f} F1={s['macro_f1']:.3f}", flush=True)
    C.write_json(results, C.RESULTS / "deductive.json")
    np.save(C.RESULTS / "deductive_assignments.npy", assignments, allow_pickle=True)
    return results


if __name__ == "__main__":
    run()
