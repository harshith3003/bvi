#!/usr/bin/env python3
"""
B1 - Per-session on-chain cost: BVI constant vs BBCA growing.

WRITE COUNT IS THE PRIMARY COMPARISON. GAS IS SECONDARY.

This ordering is deliberate and it is the defensible one. BBCA runs a modified
PBFT over a permissioned database; BVI runs on public Ethereum. Pricing BBCA's
writes in Ethereum gas compares two different cost models, and a reviewer will
say so immediately. Writes per session sidesteps that entirely: it is a
structural property of each design, countable from BBCA's own published figure,
and it does not depend on either platform's fee model.

The gas conversion is retained below the write count as an illustration only,
with its assumption stated. It is not the headline.

WHERE THE BBCA WRITE COUNT COMES FROM

BBCA publishes no gas, latency or throughput figures - Section IV defers all
experimental validation to future work. What it does publish is Figure 4, the
Call Flow Control Table, which shows one row per call event:

    1  Reg ID-1 | Call Flow ID-1 | Call initiated
    2  Reg ID-1 | Call Flow ID-2 | SBC involved
    3  Reg ID-2 | Call Flow ID-1 | Call initiated
    4  Reg ID-2 | Call Flow ID-1 | Call forwarded
    5  Reg ID-2 | Call Flow ID-1 | Roaming
    6  Reg ID-1 | Call Flow ID-1 | Call terminated
    7  Reg ID-2 | Call Flow ID-1 | Call terminated

Section III.A confirms the mechanism: "The information in the call flow control
table is updated as the call request is forwarded through different hops." A hop
transition is a write; initiation and termination are writes.

    BBCA writes = 2H          initiation and termination, per participating ISP
                + (H - 1)     one update per hop transition
                + E           SBC involvement, forwarding, roaming events

Conservative floor with E = 0:  3H - 1. For H = 2 that is 5. Their Figure 4
shows 7 for a two-ISP call that does involve an SBC, forwarding and roaming,
which is 5 plus 2 extra events. The model is consistent with their figure.

    BVI writes = 1, for every H, for every duration.
"""

import json
import os

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results")

# Measured on the local Hardhat chain. See results/table1_gas.json.
BVI_ANCHOR_GAS = 91_535
BVI_ATTEST_GAS = 116_392


def bbca_writes(H, events=0):
    """Writes per session under BBCA, per their Figure 4 structure."""
    return 2 * H + (H - 1) + events


def bvi_writes(H, duration_s=None):
    """One anchor at teardown. Independent of H and of duration."""
    return 1


def main():
    os.makedirs(RESULTS, exist_ok=True)

    print("=" * 92)
    print("B1 - PER-SESSION ON-CHAIN COST: BVI vs BBCA")
    print("=" * 92)
    print("PRIMARY COMPARISON: writes per session.")
    print("Counted from BBCA Figure 4. Platform-independent, so it does not")
    print("depend on either system's fee model.\n")

    hops = [1, 2, 3, 4, 5, 6, 7, 8]
    rows = []

    print(f"{'Hops':>5} {'BVI writes':>11} {'BBCA writes':>12} {'Ratio':>8}")
    print("-" * 92)
    for H in hops:
        bw, kw = bvi_writes(H), bbca_writes(H)
        rows.append({
            "hops": H, "bvi_writes": bw, "bbca_writes": kw,
            "write_ratio": kw / bw,
            "bvi_gas": bw * BVI_ANCHOR_GAS,
            "bbca_gas_illustrative": kw * BVI_ANCHOR_GAS,
        })
        print(f"{H:>5} {bw:>11} {kw:>12} {kw/bw:>7.0f}x")
    print("-" * 92)

    print("\nDURATION INVARIANCE (H = 4 fixed)")
    print("-" * 92)
    print(f"{'Duration':>12} {'BVI writes':>11}   Note")
    print("-" * 92)
    durations = [("30 s", 30), ("1 min", 60), ("5 min", 300),
                 ("15 min", 900), ("30 min", 1800)]
    dur_rows = []
    for label, secs in durations:
        dur_rows.append({"duration_s": secs, "bvi_writes": 1,
                         "bvi_gas": BVI_ANCHOR_GAS})
        print(f"{label:>12} {1:>11}   digest root is 32 bytes regardless of length")
    print("-" * 92)
    print("BBCA publishes no duration figure. Their cost is event-driven, and a")
    print("longer call accumulates more events (forwarding, roaming, SBC")
    print("involvement), so it is bounded below by the hop model above.")

    print("\n" + "=" * 92)
    print("SECONDARY, ILLUSTRATIVE ONLY: gas")
    print("=" * 92)
    print("BBCA runs modified PBFT on a permissioned database. It has no gas cost")
    print("in the Ethereum sense, so the column below is NOT a measured comparison.")
    print("It charges BBCA's writes at BVI's own measured per-write cost, which is")
    print("generous to BBCA since their rows carry more fields than our anchor.")
    print("Report it only as an order-of-magnitude illustration.\n")
    print(f"{'Hops':>5} {'BVI gas':>10} {'BBCA gas (illus.)':>19}")
    print("-" * 92)
    for r in rows:
        print(f"{r['hops']:>5} {r['bvi_gas']:>10,} "
              f"{r['bbca_gas_illustrative']:>19,}")
    print("-" * 92)
    print()

    distinct = None

    # ---- LaTeX ----------------------------------------------------------
    tex = [
        "% Auto-generated by experiments/bbca/bbca_cost.py. Do not edit by hand.",
        "%",
        "% WRITES ARE THE PRIMARY COMPARISON. GAS IS SECONDARY AND CAVEATED.",
        "% BBCA runs a modified PBFT over a permissioned database; pricing its",
        "% writes in Ethereum gas compares two different cost models and invites",
        "% exactly that objection. Write count is platform-neutral and derived",
        "% from their own published table structure, so it carries the argument",
        "% on its own. The gas column is retained as an illustration of what the",
        "% write count implies IF the same storage were placed on our platform,",
        "% and is explicitly not a claim about BBCA's actual cost.",
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{Per-session on-chain cost. BVI commits one fixed-size anchor at "
        "teardown, so its cost is independent of hop count and of call duration. "
        "BBCA writes one row to the Call Flow Control Table per call event "
        "(Fig.~4,~\\cite{bbca}), so its cost grows with path length. The comparison "
        "is made in \\emph{writes per session}, counted from BBCA's published table "
        "structure, because BBCA runs a modified PBFT over a permissioned database "
        "and has no gas cost in the Ethereum sense; write count is a structural "
        "property of each design and is independent of either fee model. The gas "
        "column is illustrative only: it charges BBCA's writes at BVI's own measured "
        "per-write cost, an assumption generous to BBCA since their rows carry more "
        "fields than our anchor.}",
        "\\label{tab:anchorcost}",
        "\\begin{tabular}{rrrrrr}",
        "\\toprule",
        "& \\multicolumn{3}{c}{Writes per session (primary)} & "
        "\\multicolumn{2}{c}{Gas (illustrative)} \\\\",
        "\\cmidrule(lr){2-4}\\cmidrule(lr){5-6}",
        "Hops & BVI & BBCA & Ratio & BVI & BBCA \\\\",
        "\\midrule",
    ]
    for r in rows:
        tex.append(
            f"{r['hops']} & {r['bvi_writes']} & {r['bbca_writes']} & "
            f"{r['write_ratio']:.0f}$\\times$ & {r['bvi_gas']:,} & "
            f"{r['bbca_gas_illustrative']:,} \\\\"
        )
    tex += [
        "\\midrule",
        "\\multicolumn{6}{l}{\\emph{Duration invariance, $H=4$ fixed}} \\\\",
    ]
    for label, secs in durations:
        tex.append(f"\\quad {label} & 1 & --- & --- & {BVI_ANCHOR_GAS:,} & --- \\\\")
    tex += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]

    with open(os.path.join(RESULTS, "table_b1_anchor_vs_bbca.tex"), "w") as f:
        f.write("\n".join(tex))

    with open(os.path.join(RESULTS, "b1_anchor_vs_bbca.json"), "w") as f:
        json.dump({
            "primary_metric": "writes per session",
            "bvi_anchor_gas": BVI_ANCHOR_GAS,
            "model": "BBCA writes = 2H + (H-1) + events, from their Figure 4",
            "gas_caveat": ("BBCA runs modified PBFT on a permissioned database and "
                           "has no Ethereum gas cost. The gas column charges its "
                           "writes at BVI's measured per-write cost and is "
                           "illustrative only, not a measured comparison."),
            "hop_sweep": rows,
            "duration_sweep": dur_rows,
        }, f, indent=2)

    print(f"Written to {os.path.abspath(RESULTS)}/table_b1_anchor_vs_bbca.tex")
    print(f"           {os.path.abspath(RESULTS)}/b1_anchor_vs_bbca.json\n")


if __name__ == "__main__":
    main()
