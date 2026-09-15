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



## Reproducibility

Gas figures are meaningless without the toolchain pinned. These are set in
`hardhat.config.js` and reproduced automatically in the generated table caption:

- solc **0.8.24**
- optimiser **enabled**, **200 runs**
- EVM version **paris** — deliberately not `cancun`, so the same bytecode and
  the same gas figures hold on both L1 and the rollup

If anything changes, regenerate the whole table. Don't mix.
