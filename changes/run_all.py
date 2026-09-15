#!/usr/bin/env python3
"""
UNIFIED PATH EXPERIMENT - one seed, one run, every table.

WHY THIS FILE REPLACES run_path.py AND run_b2.py
------------------------------------------------
Those two scripts each seeded their own RNG and each emitted a table. The
5-hop detection figures therefore disagreed between documents (21.4/55.9/82.1
against 20.7/58.2/84.6) and the status spread in one did not reconcile with the
detection rate in the other. Both were correct outputs of different runs, which
is exactly the problem. Every number below now comes from a single run under
SEED, and the manifest records it.

WHAT CHANGED, AND WHY

1. ONE SEED, ONE RUN. All tables derive from the same trial set, so the status
   spread divides into the detection rate by construction.

2. TWO ATTACKER MODELS.
   Average case: the tamper location is uniform over hops. This is what the
   earlier sweep measured.
   Worst case: the adversary knows which hops are attesting and picks the
   tamper point to evade observation. Closed form below.

   Detection requires at least one attesting hop upstream of the tamper and at
   least one at or downstream of it. An adversary free to choose the tamper
   point evades unless the FIRST and LAST hops both attest, because otherwise
   it can place the tamper before the first attesting hop or after the last.
   So

       worst-case detection = p^2,   independent of H.

   This matters: the path-length advantage is an average-case property and does
   NOT survive a strategic adversary. Reported as such rather than buried.

3. SPLIT METRICS. "Usable evidence" previously read 100 percent at every
   participation level, which is true under its definition but reads as a
   metric chosen to guarantee its answer. It is now two separate quantities:

     RECORD WRITTEN    a design property, not a measurement: the anchor is
                       written at teardown for every session. Stated once,
                       never tabulated across p.
     PATH EVIDENCE     the measured quantity: fraction of sessions for which
                       the path layer returns any observation at all. This
                       varies with p and is the honest number.

4. BBCA CLOSED FORM ASSERTED. Their detection is p^H. The simulator is checked
   against that at every cell, so a cell reading 0.0 percent where p^H predicts
   3.2 percent now fails the run rather than reaching a table.
"""

import json
import os
import numpy as np
from math import comb

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results")

# ---------------------------------------------------------------------------
# THE SEED. Every figure in the paper derives from this value.
# ---------------------------------------------------------------------------
SEED = 20260909
N_SESSIONS = 20000
H_VALUES = (3, 5, 8, 12)
P_GRID = tuple(round(x, 2) for x in np.arange(0.0, 1.001, 0.05))
P_REPORT = (0.0, 0.25, 0.50, 0.75, 1.0)
K = 2
TAMPER_RATE = 0.30
LEGIT_REWRITE_RATE = 0.15
Q_SBC_REGISTERED = 0.70

VERIFIED, UNKNOWN, FAILED = "verified", "unknown", "failed"


# ---------------------------------------------------------------------------
# Closed forms
# ---------------------------------------------------------------------------

def bvi_detect_average(p, H):
    """Uniform tamper location. Mean over r of two-sided visibility."""
    if H < 2:
        return 0.0
    rs = np.arange(1, H)
    return float(np.mean((1 - (1 - p) ** rs) * (1 - (1 - p) ** (H - rs))))


def bvi_detect_worst(p, H):
    """Adversary chooses the tamper point. Evades unless first and last attest."""
    return float(p * p)


def bbca_detect(p, H):
    """Unbroken hop-by-hop record required."""
    return float(p ** H)


def p_no_verdict(p, H, k):
    """Fewer than k attesting hops."""
    return float(sum(comb(H, i) * p ** i * (1 - p) ** (H - i)
                     for i in range(0, min(k, H + 1))))


def p_any_path_observation(p, H):
    """At least one attesting hop: the path layer returns something."""
    return float(1 - (1 - p) ** H)


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------

def run_session(rng, H, p, k, kind, worst_case):
    """kind in {'clean', 'malicious', 'legitimate'}.

    Returns dict with bvi status, bbca status, path-observation flag, and
    detection flags.
    """
    attests = rng.random(H) < p
    n_attest = int(attests.sum())
    any_observation = n_attest > 0

    out = {
        "n_attest": n_attest,
        "path_observed": any_observation,
        "bvi": None, "bbca": None,
        "bvi_caught": False, "bbca_caught": False,
    }

    # A legitimate rewrite by a REGISTERED SBC is expected, so the verifier does
    # not read the discontinuity as tampering.
    if kind == "legitimate" and rng.random() < Q_SBC_REGISTERED:
        kind = "clean"

    if kind == "clean":
        out["bvi"] = VERIFIED if n_attest >= k else UNKNOWN
        out["bbca"] = VERIFIED if attests.all() else UNKNOWN
        return out

    # Tampered, or a legitimate rewrite by an unregistered SBC. Identical to
    # the verifier, which is the point.
    if worst_case:
        # Adversary picks r to evade. Evasion fails only when hop 0 and hop H-1
        # both attest.
        visible = bool(attests[0] and attests[H - 1]) if H >= 2 else False
    else:
        r = int(rng.integers(1, H)) if H >= 2 else 0
        visible = bool(attests[:r].any() and attests[r:].any())

    if visible:
        out["bvi"] = FAILED
        out["bvi_caught"] = True
    else:
        out["bvi"] = UNKNOWN if n_attest < k else VERIFIED

    if attests.all():
        out["bbca"] = FAILED
        out["bbca_caught"] = True
    else:
        out["bbca"] = UNKNOWN

    return out


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def sweep(rng, worst_case):
    rows = []
    for H in H_VALUES:
        for p in P_GRID:
            counts = {VERIFIED: 0, UNKNOWN: 0, FAILED: 0}
            bbca_counts = {VERIFIED: 0, UNKNOWN: 0, FAILED: 0}
            observed = 0
            n_tamper = bvi_caught = bbca_caught = 0
            n_benign = false_demote = 0

            for _ in range(N_SESSIONS):
                roll = rng.random()
                if roll < TAMPER_RATE:
                    kind = "malicious"
                elif roll < TAMPER_RATE + LEGIT_REWRITE_RATE:
                    kind = "legitimate"
                else:
                    kind = "clean"

                r = run_session(rng, H, p, K, kind, worst_case)
                counts[r["bvi"]] += 1
                bbca_counts[r["bbca"]] += 1
                observed += int(r["path_observed"])

                if kind == "malicious":
                    n_tamper += 1
                    bvi_caught += int(r["bvi_caught"])
                    bbca_caught += int(r["bbca_caught"])
                else:
                    n_benign += 1
                    false_demote += int(r["bvi"] == FAILED)

            rows.append({
                "H": H, "p": float(p), "k": K, "n_sessions": N_SESSIONS,
                "attacker": "worst" if worst_case else "average",
                "bvi_status": {s: counts[s] / N_SESSIONS for s in counts},
                "bbca_status": {s: bbca_counts[s] / N_SESSIONS for s in bbca_counts},
                # SPLIT METRIC 1 (measured): does the path layer return anything?
                "path_evidence_rate": observed / N_SESSIONS,
                "path_evidence_closed_form": p_any_path_observation(p, H),
                # detection, conditional on a tamper actually occurring
                "bvi_detection": bvi_caught / max(1, n_tamper),
                "bvi_detection_closed_form": (bvi_detect_worst(p, H) if worst_case
                                              else bvi_detect_average(p, H)),
                "bbca_detection": bbca_caught / max(1, n_tamper),
                "bbca_detection_closed_form": bbca_detect(p, H),
                "false_demotion_rate": false_demote / max(1, n_benign),
                "no_verdict_rate": counts[UNKNOWN] / N_SESSIONS,
                "no_verdict_closed_form": p_no_verdict(p, H, K),
                "n_tamper": n_tamper, "n_benign": n_benign,
            })
    return rows


def check_against_closed_form(rows, n_sigma=4.0):
    """Fail the run rather than let a wrong cell reach a table.

    The tolerance is the binomial standard error of the relevant sample, not a
    flat number. This matters because the metrics have different sample sizes:
    detection is conditional on a tamper occurring, so it is measured on
    roughly TAMPER_RATE * N_SESSIONS trials, while path evidence is measured on
    all of them. A flat threshold either passes a real bug on the large sample
    or flags ordinary noise on the small one.

        SE = sqrt(cf * (1 - cf) / n)
        tolerance = max(0.003, n_sigma * SE)

    At 4 sigma a correct implementation trips this about once per sixteen
    thousand cells, while a cell reading 0.0 where the closed form predicts
    3.2 percent trips it by a wide margin.
    """
    problems = []
    for r in rows:
        n_tamper = max(1, r["n_tamper"])
        checks = (
            ("bvi_detection", r["bvi_detection"], r["bvi_detection_closed_form"], n_tamper),
            ("bbca_detection", r["bbca_detection"], r["bbca_detection_closed_form"], n_tamper),
            ("path_evidence", r["path_evidence_rate"], r["path_evidence_closed_form"], r["n_sessions"]),
            ("no_verdict", r["no_verdict_rate"], r["no_verdict_closed_form"], r["n_sessions"]),
        )
        for label, sim, cf, n in checks:
            se = (cf * (1 - cf) / n) ** 0.5
            tol = max(0.003, n_sigma * se)
            if abs(sim - cf) > tol:
                problems.append(
                    f"H={r['H']} p={r['p']:.2f} {r['attacker']} {label}: "
                    f"sim {sim:.4f} vs closed form {cf:.4f} "
                    f"(diff {abs(sim-cf):.4f}, tol {tol:.4f}, n={n})"
                )
    return problems


def at(rows, H, p, attacker):
    """Exact lookup. No nearest-match, which is what produced a mislabelled
    cell when 0.75 tied between the 0.7 and 0.8 grid points."""
    for r in rows:
        if r["H"] == H and abs(r["p"] - p) < 1e-9 and r["attacker"] == attacker:
            return r
    raise KeyError(f"no cell for H={H} p={p} attacker={attacker}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def main():
    os.makedirs(RESULTS, exist_ok=True)

    rng = np.random.default_rng(SEED)
    avg_rows = sweep(rng, worst_case=False)
    worst_rows = sweep(rng, worst_case=True)
    all_rows = avg_rows + worst_rows

    print("=" * 100)
    print("UNIFIED PATH EXPERIMENT")
    print("=" * 100)
    print(f"seed {SEED} | {N_SESSIONS:,} sessions per cell | k={K} | "
          f"{TAMPER_RATE:.0%} tampered, {LEGIT_REWRITE_RATE:.0%} legitimate rewrite")
    print("Every table below comes from this single run.\n")

    problems = check_against_closed_form(all_rows)
    if problems:
        print("!! CLOSED-FORM CHECK FAILED")
        for p in problems[:20]:
            print("   " + p)
        print(f"   ({len(problems)} total)\n")
        raise SystemExit(1)
    print("closed-form check: all cells agree within Monte Carlo tolerance\n")

    # ---- Table A: detection, both attacker models ------------------------
    print("TABLE A - DETECTION OF AN IN-PATH REWRITE")
    print("-" * 100)
    print("Average case: tamper location uniform. Worst case: adversary knows the")
    print("attesting set and picks the tamper point. BBCA requires an unbroken record.\n")
    print(f"{'H':>4} {'p':>6} {'BVI avg':>9} {'BVI worst':>11} {'BBCA':>8} "
          f"{'BBCA p^H':>10}")
    print("-" * 100)
    for H in H_VALUES:
        for p in P_REPORT:
            a = at(avg_rows, H, p, "average")
            w = at(worst_rows, H, p, "worst")
            print(f"{H:>4} {p:>6.2f} {a['bvi_detection']*100:>8.1f}% "
                  f"{w['bvi_detection']*100:>10.1f}% "
                  f"{a['bbca_detection']*100:>7.1f}% "
                  f"{a['bbca_detection_closed_form']*100:>9.2f}%")
        print()

    # ---- The inversion, and whether it survives -------------------------
    print("TABLE B - PARTICIPATION NEEDED FOR 50% DETECTION")
    print("-" * 100)
    print(f"{'H':>4} {'BVI average':>13} {'BVI worst':>11} {'BBCA':>8}")
    print("-" * 100)
    inversion = []
    for H in H_VALUES:
        a = sorted((r for r in avg_rows if r["H"] == H), key=lambda x: x["p"])
        w = sorted((r for r in worst_rows if r["H"] == H), key=lambda x: x["p"])
        pa = next((r["p"] for r in a if r["bvi_detection"] >= 0.5), None)
        pw = next((r["p"] for r in w if r["bvi_detection"] >= 0.5), None)
        pb = next((r["p"] for r in a if r["bbca_detection"] >= 0.5), None)
        inversion.append({"H": H, "bvi_avg_p50": pa, "bvi_worst_p50": pw,
                          "bbca_p50": pb})
        f = lambda v: f"{v:.2f}" if v is not None else "never"
        print(f"{H:>4} {f(pa):>13} {f(pw):>11} {f(pb):>8}")
    print("-" * 100)
    print("READ THIS CAREFULLY. Under the average case BVI needs LESS")
    print("participation as the path lengthens; BBCA needs more. Under the worst")
    print("case BVI's requirement is FLAT in H, because worst-case detection is")
    print("p^2 regardless of path length. The path-length advantage is therefore")
    print("an average-case property and must be reported as one. BVI still beats")
    print("BBCA in both models, by a wide margin, and that part does survive.\n")

    # ---- Split metrics ---------------------------------------------------
    print("TABLE C - PATH EVIDENCE AVAILABILITY  (H=5)")
    print("-" * 100)
    print("The measured quantity: fraction of sessions for which the path layer")
    print("returns any observation. Record existence is a separate design")
    print("property and is stated once below, not tabulated across p.\n")
    print(f"{'p':>6} {'path evidence':>15} {'verified':>10} {'no verdict':>12} "
          f"{'failed':>9} {'BBCA record':>13}")
    print("-" * 100)
    for p in P_REPORT:
        a = at(avg_rows, 5, p, "average")
        bbca_complete = a["bbca_status"][VERIFIED] + a["bbca_status"][FAILED]
        print(f"{p:>6.2f} {a['path_evidence_rate']*100:>14.1f}% "
              f"{a['bvi_status'][VERIFIED]*100:>9.1f}% "
              f"{a['bvi_status'][UNKNOWN]*100:>11.1f}% "
              f"{a['bvi_status'][FAILED]*100:>8.1f}% "
              f"{bbca_complete*100:>12.1f}%")
    print("-" * 100)
    print("DESIGN PROPERTY, stated separately and not as a measurement:")
    print("  A session record is written at teardown for every session, because")
    print("  the anchor commits Layer 1 and Layer 3 independently of the path.")
    print("  BBCA writes to its Call Flow Control Table only from registered")
    print("  ISPs, so a path containing an unregistered hop leaves no complete")
    print("  record. The rates above are the PATH layer only.\n")

    # ---- Reconciliation check -------------------------------------------
    #
    # THIS IS THE ARITHMETIC THAT LOOKED WRONG ON REVIEW, AND WHY IT ISN'T.
    #
    # Dividing the FAILED column by the tamper rate does not give the detection
    # rate, and the gap is not an inconsistency. FAILED counts every session the
    # verifier scored inconsistent, which is two populations:
    #
    #     failed = malicious rewrites detected
    #            + legitimate rewrites by an UNREGISTERED SBC
    #
    # The second group is the false-demotion population. A legitimate rewrite by
    # an unregistered SBC is indistinguishable from a malicious one, so it lands
    # in FAILED by construction. Subtracting it first is what reconciles the two
    # tables:
    #
    #     detection = (failed_total - false_demotions) / n_tampered
    #
    # Anyone checking failed/tamper_rate directly will land high by roughly the
    # false-demotion count, which is exactly the discrepancy that was flagged.
    # The tables were consistent; the reconciliation formula was not.
    print("RECONCILIATION  (FAILED must decompose into detection + false demotion)")
    print("-" * 100)
    ok_all = True
    for H in H_VALUES:
        for p in (0.25, 0.50, 0.75):
            a = at(avg_rows, H, p, "average")
            failed_n = a["bvi_status"][FAILED] * a["n_sessions"]
            fd_n = a["false_demotion_rate"] * a["n_benign"]
            implied = (failed_n - fd_n) / max(1, a["n_tamper"])
            diff = abs(implied - a["bvi_detection"])
            ok = diff < 1e-6
            ok_all &= ok
            naive = failed_n / max(1, a["n_tamper"])
            print(f"H={H:>2} p={p:.2f} | failed {failed_n:>6.0f} "
                  f"- false demote {fd_n:>5.0f} = {failed_n-fd_n:>6.0f} "
                  f"over {a['n_tamper']:>5} tampered -> {implied*100:>5.1f}% "
                  f"| reported {a['bvi_detection']*100:>5.1f}% "
                  f"| naive failed/tamper {naive*100:>5.1f}% "
                  f"| {'OK' if ok else 'MISMATCH'}")
    print("-" * 100)
    print("The 'naive' column is what you get dividing FAILED straight through by")
    print("the tamper count. It reads high because FAILED also contains the")
    print("false demotions. Once those are subtracted the two tables agree")
    print(f"exactly. All cells: {'OK' if ok_all else 'MISMATCH'}")
    print("-" * 100 + "\n")

    # ---- False demotion --------------------------------------------------
    print("FALSE DEMOTION  (benign sessions scored failed)")
    print("-" * 100)
    print(f"{'p':>6} {'H=3':>8} {'H=5':>8} {'H=8':>8} {'H=12':>8}")
    print("-" * 100)
    for p in P_REPORT:
        cells = [f"{at(avg_rows, H, p, 'average')['false_demotion_rate']*100:7.2f}%"
                 for H in H_VALUES]
        print(f"{p:>6.2f} " + " ".join(cells))
    print("-" * 100)
    print("Driven entirely by legitimate rewrites from unregistered SBCs")
    print(f"({1-Q_SBC_REGISTERED:.0%} of legitimate rewrites reach the verifier as")
    print("indistinguishable from tampering).")
    print()
    print("CORRECTION TO AN EARLIER CLAIM. This rate is NOT flat in p. It RISES")
    print("with participation, from 0 at p=0 to roughly 6 percent at p=1, because")
    print("seeing a rewrite at all requires attesting hops either side of it -")
    print("the same mechanism that produces true detection also produces the")
    print("false ones. So carrier participation trades detection against false")
    print("demotion, and the ceiling is set by SBC registration coverage:")
    print(f"at {Q_SBC_REGISTERED:.0%} SBC registration the asymptote is")
    print(f"{(1-Q_SBC_REGISTERED)*LEGIT_REWRITE_RATE/(1-TAMPER_RATE)*100:.1f}% of benign sessions.")
    print("Recruiting carriers raises both numbers; registering SBCs lowers only")
    print("the false one. That is the operational finding.\n")

    # ---- Outputs ---------------------------------------------------------
    manifest = {
        "seed": SEED,
        "n_sessions_per_cell": N_SESSIONS,
        "k": K,
        "tamper_rate": TAMPER_RATE,
        "legit_rewrite_rate": LEGIT_REWRITE_RATE,
        "q_sbc_registered": Q_SBC_REGISTERED,
        "H_values": list(H_VALUES),
        "p_grid": list(P_GRID),
        "closed_forms": {
            "bvi_average": "mean over r of (1-(1-p)^r)(1-(1-p)^(H-r))",
            "bvi_worst": "p^2, independent of H",
            "bbca": "p^H",
            "path_evidence": "1-(1-p)^H",
            "no_verdict": "binomial tail below k",
        },
        "note": ("Every table in the paper derives from this single run. "
                 "Do not regenerate a subset."),
    }

    with open(os.path.join(RESULTS, "path_unified.json"), "w") as f:
        json.dump({"manifest": manifest, "rows": all_rows,
                   "inversion": inversion}, f, indent=2)

    with open(os.path.join(RESULTS, "path_unified.csv"), "w") as f:
        f.write("attacker,H,p,k,path_evidence,bvi_verified,bvi_no_verdict,"
                "bvi_failed,bvi_detection,bvi_detection_cf,bbca_detection,"
                "bbca_detection_cf,false_demotion\n")
        for r in all_rows:
            f.write(f"{r['attacker']},{r['H']},{r['p']},{r['k']},"
                    f"{r['path_evidence_rate']:.5f},"
                    f"{r['bvi_status'][VERIFIED]:.5f},"
                    f"{r['bvi_status'][UNKNOWN]:.5f},"
                    f"{r['bvi_status'][FAILED]:.5f},"
                    f"{r['bvi_detection']:.5f},{r['bvi_detection_closed_form']:.5f},"
                    f"{r['bbca_detection']:.5f},{r['bbca_detection_closed_form']:.5f},"
                    f"{r['false_demotion_rate']:.5f}\n")

    # ---- LaTeX: detection, both models -----------------------------------
    tex = [
        "% Auto-generated by experiments/path/run_all.py.",
        f"% seed {SEED}, {N_SESSIONS:,} sessions per cell. Single run.",
        "\\begin{table}[t]", "\\centering",
        "\\caption{Detection of an in-path identifier rewrite. "
        f"{N_SESSIONS:,} simulated sessions per cell, single run at seed {SEED}. "
        "\\emph{Average} places the tamper uniformly over hops. \\emph{Worst} "
        "gives the adversary knowledge of the attesting set and free choice of "
        "tamper point; detection is then $p^2$ irrespective of $H$, since "
        "evasion fails only when both the first and last hop attest. BBCA "
        "requires an unbroken hop-by-hop record, giving $p^H$. The path-length "
        "advantage visible in the average column is an average-case property "
        "and does not survive a strategic adversary; the margin over BBCA does.}",
        "\\label{tab:pathdetect}",
        "\\begin{tabular}{rrrrr}", "\\toprule",
        "$H$ & $p$ & BVI average & BVI worst & BBCA \\\\", "\\midrule",
    ]
    for H in H_VALUES:
        for p in P_REPORT:
            a = at(avg_rows, H, p, "average")
            w = at(worst_rows, H, p, "worst")
            lead = f"{H}" if p == P_REPORT[0] else ""
            tex.append(f"{lead} & {p:.2f} & {a['bvi_detection']*100:.1f}\\% & "
                       f"{w['bvi_detection']*100:.1f}\\% & "
                       f"{a['bbca_detection']*100:.1f}\\% \\\\")
        tex.append("\\addlinespace")
    tex += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    with open(os.path.join(RESULTS, "table_path_detection.tex"), "w") as f:
        f.write("\n".join(tex))

    # ---- LaTeX: split metrics -------------------------------------------
    tex2 = [
        "% Auto-generated by experiments/path/run_all.py.",
        f"% seed {SEED}. Same run as Table~\\ref{{tab:pathdetect}}.",
        "\\begin{table}[t]", "\\centering",
        "\\caption{Path layer output at $H=5$. \\emph{Path evidence} is the "
        "measured fraction of sessions for which the path layer returns any "
        "observation, $1-(1-p)^H$. The three status columns partition all "
        "sessions. \\emph{BBCA record} is the fraction for which a complete "
        "Call Flow Control Table record exists, which requires every hop to be "
        "a registered ISP. Session record existence is a separate design "
        "property --- the anchor is written at teardown irrespective of path "
        "participation --- and is stated in the text rather than tabulated, "
        "since it does not vary with $p$.}",
        "\\label{tab:pathevidence}",
        "\\begin{tabular}{rrrrrr}", "\\toprule",
        "$p$ & Path evidence & Verified & $\\bot$ & Failed & BBCA record \\\\",
        "\\midrule",
    ]
    for p in P_REPORT:
        a = at(avg_rows, 5, p, "average")
        bc = a["bbca_status"][VERIFIED] + a["bbca_status"][FAILED]
        tex2.append(f"{p:.2f} & {a['path_evidence_rate']*100:.1f}\\% & "
                    f"{a['bvi_status'][VERIFIED]*100:.1f}\\% & "
                    f"{a['bvi_status'][UNKNOWN]*100:.1f}\\% & "
                    f"{a['bvi_status'][FAILED]*100:.1f}\\% & "
                    f"{bc*100:.1f}\\% \\\\")
    tex2 += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    with open(os.path.join(RESULTS, "table_path_evidence.tex"), "w") as f:
        f.write("\n".join(tex2))

    print(f"Written to {os.path.abspath(RESULTS)}/")
    print("  path_unified.json   full run, both attacker models")
    print("  path_unified.csv    same, flat")
    print("  table_path_detection.tex")
    print("  table_path_evidence.tex")
    print("\nThese supersede table3_path_coverage.tex and "
          "table_b2_participation.tex.")
    print("Delete the old two so they cannot be pasted by mistake.\n")


if __name__ == "__main__":
    main()
