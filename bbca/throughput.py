#!/usr/bin/env python3
"""
B4 - Anchor throughput ceiling.

THE QUESTION: how many sessions per second can be anchored before the chain
becomes the bottleneck, and does that clear Australian call volume?

THE METHOD: throughput is bounded by block gas limit divided by per-anchor gas,
divided by block time. Every input is a published protocol parameter or a
measured figure from Table 1, so the ceiling is derived rather than asserted.

    anchors per block  = block_gas_limit / anchor_gas
    anchors per second = anchors per block / block_time_s
    anchors per day    = anchors per second * 86400

WHAT THIS DOES NOT MODEL: contention with other traffic on the same chain. The
figures below are the ceiling for a chain carrying only BVI anchors. A shared
chain gives BVI some fraction of that. This is stated in the caption rather
than buried, because a reviewer will ask.

CALL VOLUME: the Australian figure below is a placeholder derived from a
per-capita estimate and MUST be replaced with the ACMA Communications Report
figure before submission. It is marked clearly in the output. Do not publish
the placeholder.
"""

import json
import os

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results")

ANCHOR_GAS = 91_535       # measured, Table 1
ATTEST_GAS = 116_392      # measured, Table 1

# Chain parameters. Published protocol values; verify against current docs
# before submission since rollup parameters change.
CHAINS = [
    # (name, block gas limit, block time seconds, note)
    ("Ethereum L1",      36_000_000,  12.0, "for reference only; cost rules it out"),
    ("OP Stack L2",      60_000_000,   2.0, "Optimism-style rollup, 2 s blocks"),
    ("OP Stack L2 (high gas)", 100_000_000, 2.0, "raised block limit configuration"),
]

# PLACEHOLDER. Replace with the ACMA Communications Report figure.
AU_CALLS_PER_DAY_PLACEHOLDER = 33_000_000
AU_SOURCE_NOTE = ("PLACEHOLDER derived from a per-capita estimate. "
                  "Replace with the ACMA Communications Report figure before submission.")


def throughput(block_gas_limit, block_time_s, per_tx_gas):
    per_block = block_gas_limit / per_tx_gas
    per_second = per_block / block_time_s
    return {
        "anchors_per_block": per_block,
        "anchors_per_second": per_second,
        "anchors_per_day": per_second * 86400,
    }


def main():
    os.makedirs(RESULTS, exist_ok=True)

    print("=" * 96)
    print("B4 - ANCHOR THROUGHPUT CEILING")
    print("=" * 96)
    print(f"Anchor cost: {ANCHOR_GAS:,} gas (measured, Table 1)")
    print("Ceiling assumes the chain carries only BVI anchors. A shared chain")
    print("gives BVI a fraction of this. Stated explicitly in the caption.\n")

    print(f"{'Chain':<26} {'Limit':>12} {'Block':>7} {'/block':>8} "
          f"{'/second':>10} {'/day':>14}")
    print("-" * 96)

    rows = []
    for name, limit, btime, note in CHAINS:
        t = throughput(limit, btime, ANCHOR_GAS)
        rows.append({"chain": name, "block_gas_limit": limit,
                     "block_time_s": btime, "note": note, **t})
        print(f"{name:<26} {limit:>12,} {btime:>6.0f}s {t['anchors_per_block']:>8.0f} "
              f"{t['anchors_per_second']:>10.0f} {t['anchors_per_day']:>14,.0f}")

    print("-" * 96)

    # ---- Against call volume --------------------------------------------
    print("\nAGAINST AUSTRALIAN CALL VOLUME")
    print("-" * 96)
    print(f"!! {AU_SOURCE_NOTE}")
    print(f"   Working figure: {AU_CALLS_PER_DAY_PLACEHOLDER:,} calls/day\n")

    print(f"{'Chain':<26} {'Capacity/day':>16} {'Headroom':>12} {'Verdict':>28}")
    print("-" * 96)
    for r in rows:
        headroom = r["anchors_per_day"] / AU_CALLS_PER_DAY_PLACEHOLDER
        verdict = ("clears with headroom" if headroom >= 2
                   else "clears, little margin" if headroom >= 1
                   else "does NOT clear unbatched")
        r["headroom_vs_au"] = headroom
        r["clears_au"] = headroom >= 1
        print(f"{r['chain']:<26} {r['anchors_per_day']:>16,.0f} "
              f"{headroom:>11.1f}x {verdict:>28}")
    print("-" * 96)

    # ---- What batching buys ---------------------------------------------
    # Batching amortises the 21,000 intrinsic transaction cost and the calldata
    # overhead across N anchors in one transaction. The three cold SSTOREs per
    # anchor cannot be avoided - that storage must be written either way - so
    # batching has a hard floor.
    INTRINSIC = 21_000
    CALLDATA_PER_ANCHOR = 100 * 16      # 3 words + selector share, non-zero bytes
    STORAGE_PER_ANCHOR = 91_535 - INTRINSIC - CALLDATA_PER_ANCHOR

    print("\nWHAT BATCHING BUYS")
    print("-" * 96)
    print("Batching amortises the 21,000 gas intrinsic transaction cost across N")
    print("anchors. The three cold storage writes per anchor cannot be amortised -")
    print("that state must be written regardless - so there is a hard floor.\n")
    print(f"{'Batch size':>11} {'Gas/anchor':>12} {'Saving':>9} {'Throughput gain':>17}")
    print("-" * 96)

    batch_rows = []
    for n in (1, 2, 5, 10, 25, 50, 100):
        per_anchor = (INTRINSIC / n) + CALLDATA_PER_ANCHOR + STORAGE_PER_ANCHOR
        saving = 1 - per_anchor / ANCHOR_GAS
        gain = ANCHOR_GAS / per_anchor
        batch_rows.append({"batch_size": n, "gas_per_anchor": per_anchor,
                           "saving_fraction": saving, "throughput_gain": gain})
        print(f"{n:>11} {per_anchor:>12,.0f} {saving*100:>8.1f}% {gain:>16.2f}x")

    print("-" * 96)
    floor = CALLDATA_PER_ANCHOR + STORAGE_PER_ANCHOR
    print(f"Asymptotic floor: {floor:,} gas per anchor "
          f"({ANCHOR_GAS/floor:.2f}x throughput gain).")
    print("Storage writes dominate, so batching buys roughly 25 percent and no more.")
    print("The honest conclusion is that batching is not the lever; the L2 choice is.\n")

    out = {
        "anchor_gas": ANCHOR_GAS,
        "chains": rows,
        "au_calls_per_day": AU_CALLS_PER_DAY_PLACEHOLDER,
        "au_source_note": AU_SOURCE_NOTE,
        "batching": batch_rows,
        "batching_floor_gas": floor,
        "caveat": ("Ceiling assumes a chain carrying only BVI anchors. "
                   "Contention with other traffic reduces available throughput."),
    }
    with open(os.path.join(RESULTS, "b4_throughput.json"), "w") as f:
        json.dump(out, f, indent=2)

    # ---- LaTeX ----------------------------------------------------------
    tex = [
        "% Auto-generated by experiments/throughput/throughput.py.",
        "\\begin{table}[t]", "\\centering",
        "\\caption{Anchor throughput ceiling. Derived from published block gas "
        "limits and the measured anchor cost of "
        f"{ANCHOR_GAS:,}~gas (Table~\\ref{{tab:gas}}). Figures assume a chain "
        "carrying only BVI anchors; a shared chain yields a proportional fraction. "
        "Batching amortises the 21{,}000~gas intrinsic transaction cost but not the "
        "three cold storage writes per anchor, giving an asymptotic floor of "
        f"{floor:,}~gas and a throughput gain bounded at "
        f"{ANCHOR_GAS/floor:.2f}$\\times$. Call volume figure requires replacement "
        "with the ACMA Communications Report value.}",
        "\\label{tab:throughput}",
        "\\begin{tabular}{lrrrr}", "\\toprule",
        "Chain & Block limit & Block time & Anchors/s & Anchors/day \\\\",
        "\\midrule",
    ]
    for r in rows:
        tex.append(f"{r['chain']} & {r['block_gas_limit']:,} & "
                   f"{r['block_time_s']:.0f}\\,s & {r['anchors_per_second']:,.0f} & "
                   f"{r['anchors_per_day']:,.0f} \\\\")
    tex += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]

    with open(os.path.join(RESULTS, "table_b4_throughput.tex"), "w") as f:
        f.write("\n".join(tex))

    print(f"Written to {os.path.abspath(RESULTS)}/table_b4_throughput.tex")
    print(f"           {os.path.abspath(RESULTS)}/b4_throughput.json\n")


if __name__ == "__main__":
    main()
