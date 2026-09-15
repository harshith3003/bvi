# Response to review — all 8 points

Every table now comes from **one seeded run**. Seed `20260909`, recorded in
`results/path_unified.json` under `manifest`.

---

## 1. Wrong cell — BBCA 12 hops, 75%

**You were right.** Two separate faults:

- The LaTeX generator picked the nearest grid point to `p=0.75`, and 0.75 sat
  exactly between 0.7 and 0.8, so it silently took 0.7.
- The value then got hand-transcribed into the Word doc as 0.0%.

Fixed by exact lookup (no nearest-match) plus a closed-form assertion on
**every** cell. Correct value is **3.4%** (closed form 3.17%).

The check uses binomial standard error, not a flat tolerance, because
detection is measured on the ~6,000 tampered sessions while path evidence is
measured on all 20,000. A flat threshold either misses real bugs on the large
sample or flags noise on the small one.

---

## 2. Same experiment, two sets of numbers

`run_path.py` and `run_b2.py` each seeded their own RNG. Both outputs were
valid; they were different runs.

Replaced by **`experiments/path/run_all.py`** — one seed, one run, every table.
Old files deleted so they can't be pasted by mistake.

### Your Table 4 / Table 6 arithmetic

Your check was reasonable but the formula overstates detection. `FAILED`
contains two populations:

```
FAILED = malicious rewrites detected + legitimate rewrites by an unregistered SBC
```

The second group is the false-demotion population — indistinguishable from
tampering, so it lands in `FAILED` by construction. The identity is:

```
detection = (FAILED − false demotions) / tampered
```

At H=5, p=0.50: `(3887 − 528) / 5933 = 56.6%` — exactly the reported figure.
Dividing straight through gives 65.5%. At H=8, p=0.75 the naive form gives
**103.8%**, which is impossible and confirms it was the formula.

This now runs as an assertion on every cell.

---

## 3. "100% usable evidence at 0% participation"

Agreed — split into two, as you suggested.

**Design property** (stated once, not tabulated): the anchor is written at
teardown for every session, because it commits Layers 1 and 3 independently of
the path.

**Measured metric** (varies, `table_path_evidence.tex`):

| p | Path evidence | Verified | ⊥ | Failed | BBCA record |
|---|---|---|---|---|---|
| 0.00 | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| 0.25 | 75.7% | 29.0% | 63.8% | 7.2% | 0.1% |
| 0.50 | 96.9% | 62.0% | 18.6% | 19.4% | 3.1% |
| 0.75 | 99.9% | 69.6% | 1.5% | 28.9% | 23.9% |

Path evidence is `1−(1−p)^H`, asserted against closed form.

---

## 4. Worst-case attacker — **the inversion does not survive**

You were right to push. Closed form:

Detection needs an attesting hop upstream of the tamper and one at or
downstream. An adversary who sees the attesting set and picks the tamper point
evades unless **both the first and last hop attest**. So:

```
worst-case detection = p²,  independent of H
```

Simulation confirms to 3 decimals.

**Participation for 50% detection:**

| H | BVI average | BVI worst | BBCA |
|---|---|---|---|
| 3 | 0.60 | 0.75 | 0.80 |
| 5 | 0.50 | 0.75 | 0.90 |
| 8 | 0.35 | 0.75 | 0.95 |
| 12 | **0.25** | **0.75** | 0.95 |

Flat in H under worst case. **So we report the inversion as average-case only,
with the assumption stated.**

What does survive both models is the margin over BBCA. At p=0.5, H=12:
worst-case BVI 24.6% vs BBCA 0.02%. At H=5: 24.8% vs 3.1%. The first claim
doesn't depend on tamper location.

---

## 5. Metadata exposure + who pays

Both drafted in `paper_corrections.tex` blocks 2 and 3.

**Exposure:** contents hashed, incidence not. Volume per submitting address and
diurnal pattern are public. Three mitigations noted, none evaluated — rotating
addresses, batching, or a permissioned chain (which forfeits R2).

**Who pays:** the originating organisation's gateway, not the recipient — R2
forces that. Scales with that organisation's own volume, not network size.
Flagged the open governance question: nobody naturally funds contract
deployment or the registrar's accreditation function.

---

## 6. BBCA wording

Agreed, the earlier phrasing overstated it. Their Section III.A says only
registered ISPs may write, then says **nothing** about an unregistered hop — no
fallback, no partial verdict, no degraded mode.

New wording: **"BBCA defines no behaviour for an unregistered hop"** — narrower
and checkable against their text. Not "requires universal participation", which
is our inference and appears nowhere in their paper.

---

## 7. Writes primary, gas secondary

Done. Write count now leads and is bolded; gas moved right with an explicit
disclaimer that BBCA runs PBFT over a permissioned database and the gas column
states what their write count would cost *if the same storage were on our
platform* — not a claim about their actual cost.

| Hops | BVI writes | BBCA writes | Ratio |
|---|---|---|---|
| 2 | 1 | 5 | 5× |
| 5 | 1 | 14 | 14× |
| 8 | 1 | 23 | 23× |

---

## 8. Splice FPR + the 53→8% step

**The step wasn't real.** It came from an inconsistently derived threshold.
With thresholds held at fixed FPR the curve is monotone:

| Splice | Frames | Local BER | Windowed BER | det@1% | det@5% | det@10% |
|---|---|---|---|---|---|---|
| 2% | 8 | 0.469 | 0.182 | 13.9% | 19.4% | 19.4% |
| 5% | 20 | 0.472 | 0.223 | 25.0% | 27.8% | 30.6% |
| 10% | 40 | 0.469 | 0.268 | 36.1% | 38.9% | 41.7% |
| 15% | 60 | 0.498 | 0.383 | 63.9% | 66.7% | 69.4% |
| 100% | 400 | 0.498 | 0.547 | 100% | 100% | 100% |

**Mechanism:** local BER on the spliced frames is ~0.47 at every length — the
substitution is always visible in principle. The windowed maximum is lower
because any window containing a short splice also contains matching frames.
The floor is the **shortest analysis window, ~240 ms**.

It's tunable, not a limit (`table_window_ablation.tex`):

| Window scales | Benign p99 | 5% splice | 10% | 25% |
|---|---|---|---|---|
| (12, 25, 50) | 0.372 | 25.0% | 33.3% | 77.8% |
| (6, 12, 25) | 0.438 | 36.1% | 38.9% | 91.7% |
| (4, 8, 16) | 0.427 | **41.7%** | 44.4% | 91.7% |

**One thing worth knowing for the real-corpus run:** only **12–17%** of spliced
frames were voiced in the synthetic corpus, and the gated comparison ignores
unvoiced frames by design. Real speech carries a much higher voiced fraction, so
these figures should **improve**, not degrade. We should report voiced fraction
alongside the result.

---

## Files

**New — use these:**
- `table_path_detection.tex` — both attacker models
- `table_path_evidence.tex` — split metrics
- `table_splice_fpr.tex` — detection at fixed FPR
- `table_window_ablation.tex` — resolution tradeoff
- `paper_corrections.tex` — 7 text blocks, each labelled
- `path_unified.json` / `.csv` — full run + manifest

**Deleted:** `table3_path_coverage.tex`, `table_b2_participation.tex`,
`table2_separability.tex` — superseded, removed so they can't be pasted.

**To re-run:**
```bash
cd experiments/path   && python3 run_all.py
cd experiments/digest && python3 splice_diagnostic.py
cd experiments/bbca   && python3 bbca_cost.py
```

**Still outstanding:** real speech corpus, ACMA figure (using the source you
named), forced-inclusion delay.
