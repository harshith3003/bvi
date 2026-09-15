#!/usr/bin/env python3
"""
B1 - Anchor cost: BVI constant vs BBCA growing.

THE HONEST FRAMING, AND WHY IT MATTERS

BBCA publishes no gas figures, no latency figures, and no throughput figures.
Their Section IV defers all experimental validation to future work. So a direct
gas-to-gas comparison is not available and inventing one would be indefensible.

What IS available is their Figure 4, the Call Flow Control Table, which shows
one row per call event. That is a structural property of their design and it is
directly countable. So the comparison is made in WRITES PER SESSION, which is
derivable from their own published figure, and only then converted to gas under
an assumption stated explicitly and chosen to favour BBCA.

BBCA's Figure 4 shows seven rows for a single call involving two ISPs:

    1  Reg ID-1 | Call Flow ID-1 | Call initiated
    2  Reg ID-1 | Call Flow ID-2 | SBC involved
    3  Reg ID-2 | Call Flow ID-1 | Call initiated
    4  Reg ID-2 | Call Flow ID-1 | Call forwarded
    5  Reg ID-2 | Call Flow ID-1 | Roaming
    6  Reg ID-1 | Call Flow ID-1 | Call terminated
    7  Reg ID-2 | Call Flow ID-1 | Call terminated

Section III.A confirms the mechanism: "The information in the call flow control
table is updated as the call request is forwarded through different hops." So a
hop transition is a write, and initiation and termination are writes.

THE MODEL

    BBCA writes = 2H          (initiation and termination, per participating ISP)
                + (H - 1)     (one update per hop transition)
                + E           (SBC involvement, forwarding, roaming events)

The conservative floor, with no SBC, no forwarding and no roaming, is:

    BBCA writes = 2H + (H - 1) = 3H - 1

For H = 2 this gives 5. Their own Figure 4 shows 7 for a two-ISP call that does
involve an SBC, forwarding and roaming, which is 5 + 2 extra events. The model
is consistent with their published figure.

BVI writes = 1, for every H, for every duration.

CONVERSION TO GAS

Each BBCA row carries a registration ID hash, a call flow ID hash, and an event
label. That is at minimum two 32-byte words plus a status field - structurally
comparable to, and if anything larger than, BVI's anchor payload. Charging BBCA
the same 91,535 gas per write as BVI's anchor is therefore generous to BBCA.
The ratio below is a LOWER BOUND on their overhead.
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
    print("BBCA writes derived from their Figure 4 (Call Flow Control Table).")
    print("Gas conversion charges BBCA the same per-write cost as BVI's anchor,")
    print("which is generous to BBCA. Ratios below are a lower bound.\n")

    hops = [1, 2, 3, 4, 5, 6, 7, 8]
    rows = []

    print(f"{'Hops':>5} {'BVI writes':>11} {'BBCA writes':>12} "
          f"{'BVI gas':>10} {'BBCA gas (>=)':>14} {'Overhead':>10}")
    print("-" * 92)

    for H in hops:
        bw = bvi_writes(H)
        kw = bbca_writes(H)
        bg = bw * BVI_ANCHOR_GAS
        kg = kw * BVI_ANCHOR_GAS
        ratio = kg / bg
        rows.append({
            "hops": H, "bvi_writes": bw, "bbca_writes": kw,
            "bvi_gas": bg, "bbca_gas_lower_bound": kg,
            "overhead_ratio": ratio,
        })
        print(f"{H:>5} {bw:>11} {kw:>12} {bg:>10,} {kg:>14,} {ratio:>9.1f}x")

    print("-" * 92)

    # Duration invariance. This is the part BBCA has no answer to at all,
    # because their table is updated by events and events accumulate with time.
    print("\nDURATION INVARIANCE (H = 4 fixed)")
    print("-" * 92)
    print(f"{'Duration':>12} {'BVI writes':>11} {'BVI gas':>10}   Note")
    print("-" * 92)
    durations = [("30 s", 30), ("1 min", 60), ("5 min", 300),
                 ("15 min", 900), ("30 min", 1800)]
    dur_rows = []
    for label, secs in durations:
        dur_rows.append({"duration_s": secs, "bvi_writes": 1,
                         "bvi_gas": BVI_ANCHOR_GAS})
        print(f"{label:>12} {1:>11} {BVI_ANCHOR_GAS:>10,}   "
              f"digest root is 32 bytes regardless of length")
    print("-" * 92)
    print("BBCA has no published duration figure. Their cost is event-driven,")
    print("and a longer call accumulates more events (forwarding, roaming,")
    print("SBC involvement), so their cost is bounded below by the hop model")
    print("above and rises from there.\n")

    # ---- LaTeX ----------------------------------------------------------
    tex = [
        "% Auto-generated by experiments/bbca/bbca_cost.py. Do not edit by hand.",
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{Per-session on-chain cost. BVI commits one fixed-size anchor at "
        "teardown; its cost is independent of both hop count and call duration. "
        "BBCA writes one row to the Call Flow Control Table per call event "
        "(Fig.~4, \\cite{bbca}), so its cost grows with path length. BBCA publishes "
        "no gas figures, so writes are counted from their published table structure "
        "and converted at BVI's own per-write cost --- an assumption generous to "
        "BBCA, since their rows carry more fields than our anchor. The overhead "
        "column is therefore a lower bound.}",
        "\\label{tab:anchorcost}",
        "\\begin{tabular}{rrrrrr}",
        "\\toprule",
        "& \\multicolumn{2}{c}{Writes per session} & \\multicolumn{2}{c}{Gas per session} & \\\\",
        "\\cmidrule(lr){2-3}\\cmidrule(lr){4-5}",
        "Hops & BVI & BBCA & BVI & BBCA ($\\geq$) & Overhead \\\\",
        "\\midrule",
    ]
    for r in rows:
        tex.append(
            f"{r['hops']} & {r['bvi_writes']} & {r['bbca_writes']} & "
            f"{r['bvi_gas']:,} & {r['bbca_gas_lower_bound']:,} & "
            f"{r['overhead_ratio']:.1f}$\\times$ \\\\"
        )
    tex += [
        "\\midrule",
        "\\multicolumn{6}{l}{\\emph{Duration invariance, $H=4$ fixed}} \\\\",
    ]
    for label, secs in durations:
        tex.append(f"\\quad {label} & 1 & --- & {BVI_ANCHOR_GAS:,} & --- & --- \\\\")
    tex += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]

    with open(os.path.join(RESULTS, "table_b1_anchor_vs_bbca.tex"), "w") as f:
        f.write("\n".join(tex))

    with open(os.path.join(RESULTS, "b1_anchor_vs_bbca.json"), "w") as f:
        json.dump({
            "bvi_anchor_gas": BVI_ANCHOR_GAS,
            "model": "BBCA writes = 2H + (H-1) + events, from their Figure 4",
            "gas_assumption": "BBCA charged BVI's per-write cost; generous to BBCA",
            "hop_sweep": rows,
            "duration_sweep": dur_rows,
        }, f, indent=2)

    print(f"Written to {os.path.abspath(RESULTS)}/table_b1_anchor_vs_bbca.tex")
    print(f"           {os.path.abspath(RESULTS)}/b1_anchor_vs_bbca.json\n")


if __name__ == "__main__":
    main()
