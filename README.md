# BVI — Identity, Path and Content on One Ledger

Contract, tests, and measurement harness for the BVI paper.

Everything here exists to fill a specific empty table. If a file doesn't map to
a table or a claim, it shouldn't be here.

| Paper item | Produced by | Status |
|---|---|---|
| Table 1 — gas | `npm run gas` | harness ready, **run locally** |
| Table 2 — digest separability | `experiments/digest/run_digest.py` | **run**, synthetic corpus |
| Table 3 — path coverage | `experiments/path/run_path.py` | **run** |
| T4 — digest bit rate | `experiments/digest/run_digest.py` | **run**, answered |
| RQ5 — latency | `npm run latency:opsepolia` | harness ready, **run locally** |
| §4.2 unsuppressibility | `test/revocation.test.js` | harness ready |
| §5.1 constant cost | `test/claims.test.js` | harness ready |

---

## What's already run, and what isn't

This repo was assembled in a container with **no network access**, so no
`solc`, no Hardhat, no Foundry. That splits the work:

**Already run** — the pure signal-processing and simulation work, which needs no
chain. Results are in `results/`. These are the two experiments the paper's main
claims rest on, and the one blocking TODO.

**Not yet run** — anything needing a compiled contract. The harness is complete
and runnable; you need `npm install` on a machine with network access.

---

## Quick start

```bash
# Contract side (needs network for npm install)
npm install
npm test                 # full suite, including the claim-bearing tests
npm run gas              # -> results/table1_gas.{json,csv,tex}

# Experiment side (numpy/scipy only)
cd experiments/digest && python3 run_digest.py     # -> Table 2 + T4
cd experiments/path   && python3 run_path.py       # -> Table 3
cd experiments/gasmodel && python3 gas_model.py    # predicted Table 1
```

Testnet, once you have a funded key:

```bash
cp .env.example .env     # add PRIVATE_KEY
npm run deploy:opsepolia
npm run latency:opsepolia   # -> results/latency_opSepolia.json
```

---

## Layout

```
contracts/
  IBVIRegistry.sol      the interface from the paper's appendix
  BVIRegistry.sol       implementation; storage layout notes explain Table 1

test/
  claims.test.js        THE PAPER'S CLAIMS. Constant cost, gasless reads,
                        one-SLOAD membership, anchor immutability.
  revocation.test.js    §4.2 / §7.1 unsuppressibility, decomposed into four
                        separately testable properties
  identity.test.js      Layer 1 functional
  path.test.js          Layer 2 functional
  anchor.test.js        Layer 3 functional

scripts/
  measure-gas.js        Table 1, with the constant-cost sweep built in
  deploy.js             same bytecode to L1 and L2; records provenance
  measure-latency.js    RQ5; separates read latency from confirmation latency

experiments/
  digest/               robust digest, channel models, A4 attacks
  path/                 coverage sweep vs BBCA baseline
  gasmodel/             analytical prediction of Table 1 from opcode costs

results/                everything generated, in json + csv + tex
```

The `.tex` files are ready to `\input` directly. Captions carry the toolchain
provenance a reviewer will ask for.

---

## Two things to fix before submission

**1. Re-run Table 2 on real speech.** The digest numbers currently come from
synthetic source-filter signals, because the container had no corpus. They
validate the pipeline; they are not results. Point it at a real narrowband
corpus:

```bash
python3 run_digest.py --corpus /path/to/wavs
```

Aim for 50+ speakers. Expect the numbers to get worse — synthesis produces
cleaner spectro-temporal gradients than real speech, so the current separation
is optimistic.

**2. Fill in `docs/forced-inclusion.md`.** It's a docs read, not an experiment,
and it's the last piece of the §4.2 argument. Everything else about revocation
is already proved in `test/revocation.test.js`; what no Solidity test can
establish is that the transaction gets *included* promptly on a rollup.

---

## Reproducibility

Gas figures are meaningless without the toolchain pinned. These are set in
`hardhat.config.js` and reproduced automatically in the generated table caption:

- solc **0.8.24**
- optimiser **enabled**, **200 runs**
- EVM version **paris** — deliberately not `cancun`, so the same bytecode and
  the same gas figures hold on both L1 and the rollup

If you change any of these, regenerate the whole table. Don't mix.
