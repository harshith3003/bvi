#!/usr/bin/env python3
"""
B2 - Participation sweep, to specification.

REQUESTED FORMAT: a thousand sessions, carrier participation at 0, 25, 50, 75
and 100 percent, reporting the spread across the three path statuses and how
many sessions still yield usable evidence.

This differs from the coverage sweep in run_path.py, which reports detection
rate. That answers "does BVI beat BBCA." This answers a different and more
important question: "what does a verifier actually see, and can a dispute still
be resolved."

THE THREE STATUSES (Section 4)

    VERIFIED    at least k participating hops, all consistent
    FAILED      a participating hop contradicts the assertion
    UNKNOWN     fewer than k participating hops; no verdict

UNKNOWN MUST NOT FAIL THE SESSION. This is the whole point. A path nobody
attested is unobserved, not suspicious. Treating it as failure is exactly
BBCA's problem: their Call Flow Control Table has no defined behaviour for an
unregistered hop, so a path containing one yields nothing at all.

USABLE EVIDENCE is the metric that matters for the paper's evidence-log framing.
A session yields usable evidence if the anchor was written, which happens
regardless of path status, because Layer 1 and Layer 3 do not depend on carrier
participation. So BVI yields usable evidence for 100 percent of sessions at
every participation level, including zero. BBCA yields usable evidence only
when every hop is registered and participating.

That contrast is the single clearest statement of the paper's first claim.
"""

import json
import os
import numpy as np

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results")

VERIFIED = "verified"
UNKNOWN = "unknown"
FAILED = "failed"


def simulate_session(rng, H, p, k, tampered, q_sbc_registered=0.7):
    """One session. Returns (bvi_status, bvi_usable, bbca_status, bbca_usable)."""
    participates = rng.random(H) < p
    n_attest = int(participates.sum())

    # ---- BVI --------------------------------------------------------------
    if tampered:
        r = int(rng.integers(1, H)) if H >= 2 else 0
        upstream = bool(participates[:r].any())
        downstream = bool(participates[r:].any())
        if upstream and downstream:
            bvi = FAILED                    # discontinuity observed
        elif n_attest < k:
            bvi = UNKNOWN
        else:
            bvi = VERIFIED                  # tamper occurred but was not visible
    else:
        bvi = VERIFIED if n_attest >= k else UNKNOWN

    # The anchor is written at teardown regardless of path status. Layer 1 and
    # Layer 3 do not depend on carrier participation, so evidence exists for
    # every session.
    bvi_usable = True

    # ---- BBCA -------------------------------------------------------------
    # Only registered ISPs may write to the Call Flow Control Table
    # (Section III.A). A single unregistered hop breaks the record, and the
    # paper defines no behaviour for that case.
    if participates.all():
        bbca = FAILED if tampered else VERIFIED
        bbca_usable = True
    else:
        bbca = UNKNOWN
        bbca_usable = False                 # no complete record exists

    return bvi, bvi_usable, bbca, bbca_usable


def sweep(n_sessions=1000, H=5, k=2, p_values=(0.0, 0.25, 0.50, 0.75, 1.0),
          tamper_rate=0.30, seed=17):
    rng = np.random.default_rng(seed)
    rows = []

    for p in p_values:
        bvi_counts = {VERIFIED: 0, UNKNOWN: 0, FAILED: 0}
        bbca_counts = {VERIFIED: 0, UNKNOWN: 0, FAILED: 0}
        bvi_usable = bbca_usable = 0
        tampered_total = bvi_caught = bbca_caught = 0

        for _ in range(n_sessions):
            tampered = rng.random() < tamper_rate
            bvi, bu, bbca, ku = simulate_session(rng, H, p, k, tampered)

            bvi_counts[bvi] += 1
            bbca_counts[bbca] += 1
            bvi_usable += int(bu)
            bbca_usable += int(ku)

            if tampered:
                tampered_total += 1
                bvi_caught += int(bvi == FAILED)
                bbca_caught += int(bbca == FAILED)

        rows.append({
            "p": float(p), "H": H, "k": k, "n_sessions": n_sessions,
            "bvi": {s: bvi_counts[s] / n_sessions for s in bvi_counts},
            "bbca": {s: bbca_counts[s] / n_sessions for s in bbca_counts},
            "bvi_usable_evidence": bvi_usable / n_sessions,
            "bbca_usable_evidence": bbca_usable / n_sessions,
            "bvi_tamper_caught": bvi_caught / max(1, tampered_total),
            "bbca_tamper_caught": bbca_caught / max(1, tampered_total),
            "n_tampered": tampered_total,
        })

    return rows


def main():
    os.makedirs(RESULTS, exist_ok=True)
    N, H, K = 1000, 5, 2

    rows = sweep(n_sessions=N, H=H, k=K)

    print("=" * 100)
    print("B2 - PARTICIPATION SWEEP")
    print("=" * 100)
    print(f"{N:,} sessions per participation level. Path length H={H}, "
          f"k={K} attestations required for a positive verdict.")
    print("30% of sessions carry an in-path identifier rewrite.\n")

    print("PATH STATUS SPREAD")
    print("-" * 100)
    print(f"{'p':>6}  {'BVI verified':>13} {'BVI unknown':>12} {'BVI failed':>11}   "
          f"{'BBCA ver.':>10} {'BBCA unk.':>10} {'BBCA fail':>10}")
    print("-" * 100)
    for r in rows:
        print(f"{r['p']*100:>5.0f}%  "
              f"{r['bvi'][VERIFIED]*100:>12.1f}% {r['bvi'][UNKNOWN]*100:>11.1f}% "
              f"{r['bvi'][FAILED]*100:>10.1f}%   "
              f"{r['bbca'][VERIFIED]*100:>9.1f}% {r['bbca'][UNKNOWN]*100:>9.1f}% "
              f"{r['bbca'][FAILED]*100:>9.1f}%")
    print("-" * 100)

    print("\nUSABLE EVIDENCE  (a session from which a dispute can be resolved)")
    print("-" * 100)
    print(f"{'p':>6}  {'BVI':>10} {'BBCA':>10}   Note")
    print("-" * 100)
    for r in rows:
        note = ("anchor written regardless of participation"
                if r["p"] < 1.0 else "both complete at full participation")
        print(f"{r['p']*100:>5.0f}%  {r['bvi_usable_evidence']*100:>9.1f}% "
              f"{r['bbca_usable_evidence']*100:>9.1f}%   {note}")
    print("-" * 100)

    print("\nTAMPER DETECTION  (of sessions that were actually tampered)")
    print("-" * 100)
    print(f"{'p':>6}  {'BVI':>10} {'BBCA':>10}")
    print("-" * 100)
    for r in rows:
        print(f"{r['p']*100:>5.0f}%  {r['bvi_tamper_caught']*100:>9.1f}% "
              f"{r['bbca_tamper_caught']*100:>9.1f}%")
    print("-" * 100)

    print("\nTHE SENTENCE THIS TABLE SUPPORTS")
    print("-" * 100)
    z = rows[0]
    h = next(r for r in rows if abs(r["p"] - 0.5) < 1e-9)
    print(f"At zero carrier participation BVI still yields usable evidence for")
    print(f"{z['bvi_usable_evidence']*100:.0f}% of sessions, because the anchor commits")
    print(f"Layer 1 and Layer 3 independently of the path. BBCA yields")
    print(f"{z['bbca_usable_evidence']*100:.0f}%. At 50% participation BVI detects")
    print(f"{h['bvi_tamper_caught']*100:.0f}% of in-path rewrites against BBCA's")
    print(f"{h['bbca_tamper_caught']*100:.0f}%, and no session is ever demoted for")
    print("a path nobody observed.")
    print("-" * 100)

    with open(os.path.join(RESULTS, "b2_participation_sweep.json"), "w") as f:
        json.dump({"n_sessions": N, "H": H, "k": K, "rows": rows}, f, indent=2)

    # ---- LaTeX ----------------------------------------------------------
    tex = [
        "% Auto-generated by experiments/path/run_b2.py.",
        "\\begin{table}[t]", "\\centering",
        "\\caption{Path status spread and usable evidence under partial carrier "
        f"participation. {N:,} simulated sessions per level, path length $H={H}$, "
        f"$k={K}$ attestations required for a positive verdict, 30\\% of sessions "
        "carrying an in-path identifier rewrite. $\\bot$ (unknown) satisfies the "
        "conjunct and does not fail a session. A session yields usable evidence "
        "when a dispute can be resolved from it; for BVI the anchor is written at "
        "teardown irrespective of path participation, so evidence exists for every "
        "session. BBCA permits only registered ISPs to write to the Call Flow "
        "Control Table (Sec.~III.A, \\cite{bbca}), so a single unregistered hop "
        "leaves no complete record.}",
        "\\label{tab:participation}",
        "\\begin{tabular}{rrrrrrrr}", "\\toprule",
        "& \\multicolumn{3}{c}{BVI path status} & \\multicolumn{2}{c}{Usable evidence} "
        "& \\multicolumn{2}{c}{Tamper caught} \\\\",
        "\\cmidrule(lr){2-4}\\cmidrule(lr){5-6}\\cmidrule(lr){7-8}",
        "$p$ & Verified & $\\bot$ & Failed & BVI & BBCA & BVI & BBCA \\\\",
        "\\midrule",
    ]
    for r in rows:
        tex.append(
            f"{r['p']*100:.0f}\\% & {r['bvi'][VERIFIED]*100:.1f}\\% & "
            f"{r['bvi'][UNKNOWN]*100:.1f}\\% & {r['bvi'][FAILED]*100:.1f}\\% & "
            f"{r['bvi_usable_evidence']*100:.0f}\\% & "
            f"{r['bbca_usable_evidence']*100:.0f}\\% & "
            f"{r['bvi_tamper_caught']*100:.1f}\\% & "
            f"{r['bbca_tamper_caught']*100:.1f}\\% \\\\"
        )
    tex += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]

    with open(os.path.join(RESULTS, "table_b2_participation.tex"), "w") as f:
        f.write("\n".join(tex))

    print(f"\nWritten to {os.path.abspath(RESULTS)}/table_b2_participation.tex")
    print(f"           {os.path.abspath(RESULTS)}/b2_participation_sweep.json\n")


if __name__ == "__main__":
    main()
