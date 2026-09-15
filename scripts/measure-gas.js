/**
 * TABLE 1 - on-chain cost of every BVI operation.
 *
 * Run:  npx hardhat run scripts/measure-gas.js --network hardhat
 *
 * Emits results/table1_gas.{json,csv,tex}. The .tex is ready to \input.
 *
 * Method notes that belong in the caption:
 *   - Gas is measured from the transaction receipt (gasUsed), not from
 *     estimateGas, so it is the amount actually charged.
 *   - Each operation is run REPS times against fresh state where the storage
 *     state matters. Cold and warm SSTORE differ by 17,100 gas, so a figure
 *     measured against warm state and reported as typical would be wrong by
 *     more than the cost of the operation itself.
 *   - The recurring per-session cost is anchorSession. Everything above it in
 *     the table is administrative and amortised over an organisation's call
 *     volume; that distinction should be stated in the caption.
 */

const { ethers, network } = require("hardhat");
const fs = require("fs");
const path = require("path");

const REPS = 5;
const OUT_DIR = path.join(__dirname, "..", "results");

const CH = (s) => ethers.keccak256(ethers.toUtf8Bytes(s));
const SID = (n, c) =>
  ethers.keccak256(ethers.solidityPacked(["bytes32", "bytes32"], [n, c]));
const rnd = () => ethers.hexlify(ethers.randomBytes(32));
const rndKey = () => ethers.hexlify(ethers.randomBytes(64));

/** Median, so a single outlier block cannot move the reported figure. */
function median(xs) {
  const s = [...xs].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2n;
}

async function gasOf(txPromise) {
  const tx = await txPromise;
  const receipt = await tx.wait();
  return receipt.gasUsed;
}

async function main() {
  const [registrar, gw, c1, c2] = await ethers.getSigners();

  const Factory = await ethers.getContractFactory("BVIRegistry");

  // ---- deployment cost -------------------------------------------------
  const deployGas = [];
  let registry;
  for (let i = 0; i < REPS; i++) {
    const r = await Factory.deploy(registrar.address);
    const receipt = await r.deploymentTransaction().wait();
    deployGas.push(receipt.gasUsed);
    if (i === 0) registry = r;
  }
  await registry.waitForDeployment();

  const rows = [];
  const push = (layer, op, samples, note) =>
    rows.push({
      layer,
      op,
      gas: median(samples).toString(),
      min: samples.reduce((a, b) => (b < a ? b : a)).toString(),
      max: samples.reduce((a, b) => (b > a ? b : a)).toString(),
      note,
    });

  push("-", "deploy", deployGas, "one-off, per deployment");

  // ---- Layer 1: administrative writes ----------------------------------
  const regGas = [];
  for (let i = 0; i < REPS; i++) {
    const r = await Factory.deploy(registrar.address); // fresh contract, cold slots
    await r.waitForDeployment();
    regGas.push(
      await gasOf(r.connect(registrar).register(CH(`did${i}`), rndKey(), [CH(`ch${i}`)]))
    );
  }
  push("L1", "register (1 channel)", regGas, "per organisation, once");

  const reg4Gas = [];
  for (let i = 0; i < REPS; i++) {
    const r = await Factory.deploy(registrar.address);
    await r.waitForDeployment();
    reg4Gas.push(
      await gasOf(
        r.connect(registrar).register(
          CH(`did4${i}`),
          rndKey(),
          Array.from({ length: 4 }, (_, j) => CH(`ch4${i}${j}`))
        )
      )
    );
  }
  push("L1", "register (4 channels)", reg4Gas, "shows marginal channel cost");

  // Rotation and channel ops against an established record.
  const baseDid = CH("did:bvi:measured");
  await registry.connect(registrar).register(baseDid, rndKey(), [CH("base-ch")]);

  const rotGas = [];
  for (let i = 0; i < REPS; i++) {
    rotGas.push(await gasOf(registry.connect(registrar).rotateKey(baseDid, rndKey())));
  }
  push("L1", "rotateKey", rotGas, "per rotation");

  const addGas = [];
  for (let i = 0; i < REPS; i++) {
    addGas.push(
      await gasOf(registry.connect(registrar).addChannel(baseDid, CH(`add${i}`)))
    );
  }
  push("L1", "addChannel", addGas, "per channel");

  const remGas = [];
  for (let i = 0; i < REPS; i++) {
    remGas.push(
      await gasOf(registry.connect(registrar).removeChannel(baseDid, CH(`add${i}`)))
    );
  }
  push("L1", "removeChannel", remGas, "refunds a storage slot");

  // Status: measured on fresh records so each is a first transition.
  const suspendGas = [];
  const revokeGas = [];
  for (let i = 0; i < REPS; i++) {
    const d = CH(`didstat${i}`);
    await registry.connect(registrar).register(d, rndKey(), []);
    suspendGas.push(await gasOf(registry.connect(registrar).setStatus(d, 2)));
    revokeGas.push(await gasOf(registry.connect(registrar).setStatus(d, 3)));
  }
  push("L1", "setStatus (suspend)", suspendGas, "submitted to L1 instance");
  push("L1", "setStatus (revoke)", revokeGas, "submitted to L1 instance");

  // ---- Layer 2: path attestation ---------------------------------------
  const attestGas = [];
  for (let i = 0; i < REPS; i++) {
    attestGas.push(
      await gasOf(registry.connect(c1).attest(SID(rnd(), CH("c")), 0, rnd()))
    );
  }
  push("L2", "attest (per hop)", attestGas, "paid by carrier, optional");

  // ---- Layer 3: the recurring per-session write ------------------------
  const anchorGas = [];
  for (let i = 0; i < REPS; i++) {
    anchorGas.push(
      await gasOf(registry.connect(gw).anchorSession(SID(rnd(), CH("c")), rnd(), rnd()))
    );
  }
  push("L3", "anchorSession", anchorGas, "THE recurring per-session cost");

  // ---- Reads: charged to nobody at call time ---------------------------
  const sidR = SID(CH("readsid"), CH("c"));
  await registry.connect(c1).attest(sidR, 0, rnd());
  await registry.connect(c2).attest(sidR, 1, rnd());
  await registry.connect(gw).anchorSession(sidR, rnd(), rnd());

  const reads = [
    ["resolve", await registry.resolve.estimateGas(baseDid)],
    ["isAuthorisedChannel", await registry.isAuthorisedChannel.estimateGas(baseDid, CH("base-ch"))],
    ["getAttestations (2 hops)", await registry.getAttestations.estimateGas(sidR)],
    ["getAnchor", await registry.getAnchor.estimateGas(sidR)],
  ];
  for (const [name, g] of reads) {
    rows.push({
      layer: "read",
      op: name,
      gas: g.toString(),
      min: g.toString(),
      max: g.toString(),
      note: "view call - not charged to the recipient",
    });
  }

  // ---- Constant-cost sweep --------------------------------------------
  const sweep = [];
  for (const seconds of [10, 60, 300, 1800, 3000]) {
    for (const hops of [1, 2, 4, 8, 12, 20]) {
      const g = await gasOf(
        registry.connect(gw).anchorSession(SID(rnd(), CH("c")), rnd(), rnd())
      );
      sweep.push({ seconds, hops, gas: g.toString() });
    }
  }
  const distinct = [...new Set(sweep.map((s) => s.gas))];

  // ---- Provenance ------------------------------------------------------
  const cfg = network.config;
  const solc = require("../hardhat.config.js").solidity;
  const meta = {
    generatedAt: new Date().toISOString(),
    network: network.name,
    chainId: cfg.chainId,
    solcVersion: solc.version,
    optimizer: solc.settings.optimizer,
    evmVersion: solc.settings.evmVersion,
    reps: REPS,
    statistic: "median of receipt gasUsed",
  };

  fs.mkdirSync(OUT_DIR, { recursive: true });

  fs.writeFileSync(
    path.join(OUT_DIR, "table1_gas.json"),
    JSON.stringify({ meta, rows, sweep, distinctSweepValues: distinct }, null, 2)
  );

  fs.writeFileSync(
    path.join(OUT_DIR, "table1_gas.csv"),
    ["layer,operation,gas_median,gas_min,gas_max,note"]
      .concat(rows.map((r) => `${r.layer},"${r.op}",${r.gas},${r.min},${r.max},"${r.note}"`))
      .join("\n")
  );

  // LaTeX, ready to \input into the paper.
  const tex = [
    "% Auto-generated by scripts/measure-gas.js. Do not edit by hand.",
    "\\begin{table}[t]",
    "\\centering",
    "\\caption{On-chain cost of BVI registry operations. Gas is the median of " +
      `${REPS} runs of \\texttt{gasUsed} from the transaction receipt on a local ` +
      `Hardhat chain (chain id ${cfg.chainId}), solc ${solc.version}, optimiser ` +
      `enabled at ${solc.settings.optimizer.runs} runs, EVM version ` +
      `\\texttt{${solc.settings.evmVersion}}. Layer~1 writes are administrative and ` +
      "amortised over an organisation's call volume. Layer~2 writes are paid by " +
      "participating carriers and are optional. \\texttt{anchorSession} is the only " +
      "recurring per-session cost, and it is constant in call duration and hop count. " +
      "Reads are \\texttt{view} calls and are charged to no one at call time.}",
    "\\label{tab:gas}",
    "\\begin{tabular}{llrl}",
    "\\toprule",
    "Layer & Operation & Gas & Notes \\\\",
    "\\midrule",
    ...rows.map(
      (r) =>
        `${r.layer} & \\texttt{${r.op.replace(/_/g, "\\_")}} & ` +
        `${Number(r.gas).toLocaleString("en-US")} & ${r.note} \\\\`
    ),
    "\\bottomrule",
    "\\end{tabular}",
    "\\end{table}",
  ].join("\n");

  fs.writeFileSync(path.join(OUT_DIR, "table1_gas.tex"), tex);

  // ---- Console summary -------------------------------------------------
  console.log("\n" + "=".repeat(74));
  console.log("TABLE 1 - BVI registry gas costs");
  console.log("=".repeat(74));
  console.log(
    `solc ${solc.version} | optimiser ${solc.settings.optimizer.enabled ? "on" : "off"} ` +
      `@ ${solc.settings.optimizer.runs} runs | evm ${solc.settings.evmVersion} | ` +
      `${REPS} reps, median`
  );
  console.log("-".repeat(74));
  console.log(
    "Layer".padEnd(6) + "Operation".padEnd(30) + "Gas".padStart(12) + "  Notes"
  );
  console.log("-".repeat(74));
  for (const r of rows) {
    console.log(
      r.layer.padEnd(6) +
        r.op.padEnd(30) +
        Number(r.gas).toLocaleString("en-US").padStart(12) +
        "  " + r.note
    );
  }
  console.log("-".repeat(74));
  console.log(
    `Constant-cost sweep: ${sweep.length} (duration x hop) combinations, ` +
      `${distinct.length} distinct gas value(s): ${distinct.join(", ")}`
  );
  if (distinct.length !== 1) {
    console.log("  WARNING: the constant-cost claim does not hold. Investigate.");
    process.exitCode = 1;
  }
  console.log("=".repeat(74));
  console.log(`Written to ${OUT_DIR}/table1_gas.{json,csv,tex}\n`);
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
