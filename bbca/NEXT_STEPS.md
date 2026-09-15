# What to run, and what to paste

Everything below is done except the two items marked **YOU**.

---

## Part 1 — Run these on your Mac (10 minutes total)

Three new experiment scripts. Each writes a `.tex` straight into `results/`.

```bash
cd ~/Desktop/bvi
source venv/bin/activate      # if you made the venv inside experiments/digest,
                              # use: source experiments/digest/venv/bin/activate
```

**B1 — BVI vs BBCA cost comparison** (your strongest figure)
```bash
cd ~/Desktop/bvi/experiments/bbca && python3 bbca_cost.py
```

**B2 — participation sweep, three-status spread**
```bash
cd ~/Desktop/bvi/experiments/path && python3 run_b2.py
```

**B4 — throughput ceiling**
```bash
cd ~/Desktop/bvi/experiments/throughput && python3 throughput.py
```

**Attack scenario tests** (needs the contract compiled)
```bash
cd ~/Desktop/bvi && npx hardhat test test/scenarios.test.js
```

---

## Part 2 — Paste into Overleaf

| File in `results/` | Where it goes |
|---|---|
| `table1_gas.tex` | Section 5, Table 1 |
| `table_b1_anchor_vs_bbca.tex` | Section 5, right after Table 1 |
| `table2_separability.tex` | Section 6, RQ2 |
| `table_b2_participation.tex` | Section 6, RQ3 |
| `table3_path_coverage.tex` | Section 6, RQ3 |
| `table_b4_throughput.tex` | Section 6, throughput |
| `table_b5_coverage.tex` | Section 6, RQ4 — use `table*` (two-column) |
| `section5_bbca_comparison.tex` | Section 5 prose — three blocks, each labelled |
| `section6_evaluation_draft.tex` | Section 6 — full draft |

**Preamble additions needed:**
```latex
\usepackage{booktabs}
\usepackage{pifont}
\newcommand{\cmark}{\ding{51}}
\newcommand{\xmark}{\ding{55}}
\newcommand{\pmark}{$\circ$}
```

**BibTeX entry:**
```bibtex
@article{bbca,
  author  = {Tas, I. Melih and Baktir, Selcuk},
  title   = {Blockchain-Based Caller-ID Authentication (BBCA): A Novel
             Solution to Prevent Spoofing Attacks in VoIP/SIP Networks},
  journal = {IEEE Access},
  volume  = {12},
  pages   = {60123--60137},
  year    = {2024},
  doi     = {10.1109/ACCESS.2024.3393487}
}
```

---

## Part 3 — YOU: two things left

**1. Real speech for Table 2.** Everything else is submittable. This isn't.
```bash
cd ~/Desktop/bvi/experiments/digest
python3 run_digest.py --corpus /path/to/wavs
```

**2. Forced-inclusion delay.** Open `docs/forced-inclusion.md`, fill the
checklist from Optimism's docs. One number. Half a day.

Optional if time allows: testnet latency (`npm run deploy:opsepolia` then
`npm run latency:opsepolia`) to fill the RQ5 PENDING marker.

---

## Part 4 — Search for PENDING

Section 6 has three markers. Delete each as you fill it:
```bash
grep -n "PENDING" results/section6_evaluation_draft.tex
```

1. Real-corpus digest figures (RQ2 + threats to validity)
2. RQ5 latency percentiles
3. Forced-inclusion delay

Also replace the Australian call volume placeholder in
`experiments/throughput/throughput.py` with the ACMA Communications Report
figure, then re-run.
