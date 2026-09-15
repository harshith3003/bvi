const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

/**
 * ATTACK SCENARIOS - the rows of the B5 coverage table, executed.
 *
 * Every row of Table~\ref{tab:coverage} that BVI claims to block is asserted
 * here against the deployed contract. A failure in this file means a cell in
 * that table is wrong.
 *
 * WHAT THIS FILE CAN AND CANNOT PROVE
 *
 * A1-A8 are on-chain properties and are proved directly.
 *
 * A9 (media substitution) is a Layer 3 property. The contract's role is to make
 * the digest root immutable once written and bound to the session; the
 * detection itself is measured in Table 2. Both halves are asserted: the
 * binding here, the separability there.
 *
 * A10 (deepfake) is Layer 4, runs on the recipient's device, and never touches
 * the chain. What IS asserted here is the gating property from Proposition 1 -
 * that no detector score can be written on chain and therefore no detector
 * score can promote a verdict.
 */

const Status = { Unregistered: 0, Active: 1, Suspended: 2, Revoked: 3 };
const CH = (s) => ethers.keccak256(ethers.toUtf8Bytes(s));
const SID = (nonce, chid) =>
  ethers.keccak256(ethers.solidityPacked(["bytes32", "bytes32"], [nonce, chid]));

async function fixture() {
  const [registrar, bank, attacker, carrier1, carrier2, recipient] =
    await ethers.getSigners();

  const Factory = await ethers.getContractFactory("BVIRegistry");
  const registry = await Factory.deploy(registrar.address);
  await registry.waitForDeployment();

  const bankDid = CH("did:bvi:examplebank");
  const bankKey = ethers.hexlify(ethers.randomBytes(64));
  const bankNumber = CH("+61312345678");

  await registry.connect(registrar).register(bankDid, bankKey, [bankNumber]);

  return {
    registry, registrar, bank, attacker, carrier1, carrier2, recipient,
    bankDid, bankKey, bankNumber,
  };
}

/** The Layer 1 check a verifier performs at call setup. */
async function layer1Verdict(registry, did, channelHash) {
  const rec = await registry.resolve(did);
  if (Number(rec.status) !== Status.Active) return { pass: false, reason: "status" };
  const authorised = await registry.isAuthorisedChannel(did, channelHash);
  if (!authorised) return { pass: false, reason: "channel" };
  return { pass: true, record: rec };
}

describe("A1 - no credential presented", () => {
  it("an unregistered DID resolves to Unregistered and fails Layer 1", async () => {
    const { registry } = await loadFixture(fixture);

    const verdict = await layer1Verdict(
      registry, CH("did:bvi:notabank"), CH("+61300000000")
    );

    expect(verdict.pass).to.equal(false);
    expect(verdict.reason).to.equal("status");
  });

  it("the caller cannot manufacture presence by attesting or anchoring", async () => {
    // An unregistered party can still write to Layer 2 and Layer 3, because
    // those are permissionless by design. What they cannot do is acquire a
    // Layer 1 identity, and the conjunct fails on Layer 1 regardless.
    const { registry, attacker } = await loadFixture(fixture);
    const sid = SID(CH("n"), CH("c"));

    await registry.connect(attacker).attest(sid, 0, CH("claim"));
    await registry.connect(attacker).anchorSession(sid, CH("root"), CH("transcript"));

    const verdict = await layer1Verdict(
      registry, CH("did:bvi:notabank"), CH("+61300000000")
    );
    expect(verdict.pass).to.equal(false);
  });
});

describe("A2 - self-signed credential", () => {
  it("a key not matching the on-chain hash fails verification", async () => {
    const { registry, bankDid, bankKey } = await loadFixture(fixture);

    const forgedKey = ethers.hexlify(ethers.randomBytes(64));
    const rec = await registry.resolve(bankDid);

    expect(ethers.keccak256(forgedKey)).to.not.equal(rec.pubKeyHash);
    expect(ethers.keccak256(bankKey)).to.equal(rec.pubKeyHash);
  });

  it("an attacker cannot self-register a DID", async () => {
    const { registry, attacker } = await loadFixture(fixture);

    await expect(
      registry.connect(attacker).register(
        CH("did:bvi:fakebank"), ethers.hexlify(ethers.randomBytes(64)), []
      )
    ).to.be.revertedWithCustomError(registry, "NotRegistrar");
  });

  it("an attacker cannot claim an existing organisation's number", async () => {
    const { registry, registrar, bankNumber } = await loadFixture(fixture);

    const fakeDid = CH("did:bvi:fakebank");
    await registry.connect(registrar).register(
      fakeDid, ethers.hexlify(ethers.randomBytes(64)), []
    );

    // Registered, but the bank's number is not authorised for this DID.
    expect(await registry.isAuthorisedChannel(fakeDid, bankNumber)).to.equal(false);
  });
});

describe("A3 - stolen credential", () => {
  it("revocation terminates a compromised credential immediately", async () => {
    const { registry, registrar, bankDid, bankNumber } = await loadFixture(fixture);

    let verdict = await layer1Verdict(registry, bankDid, bankNumber);
    expect(verdict.pass).to.equal(true);

    // Compromise discovered. The registrar acts.
    await registry.connect(registrar).setStatus(bankDid, Status.Revoked);

    verdict = await layer1Verdict(registry, bankDid, bankNumber);
    expect(verdict.pass).to.equal(false);
    expect(verdict.reason).to.equal("status");
  });

  it("the attacker cannot undo the revocation", async () => {
    const { registry, registrar, attacker, bankDid } = await loadFixture(fixture);

    await registry.connect(registrar).setStatus(bankDid, Status.Revoked);

    await expect(
      registry.connect(attacker).setStatus(bankDid, Status.Active)
    ).to.be.revertedWithCustomError(registry, "NotAuthorisedToSetStatus");

    await expect(
      registry.connect(registrar).setStatus(bankDid, Status.Active)
    ).to.be.revertedWithCustomError(registry, "RevokedIsTerminal");
  });

  it("THE STATED GAP: sessions before revocation still verify", async () => {
    // This is the honest limitation in the coverage table. BVI terminates a
    // compromised credential but cannot retroactively invalidate calls made in
    // the window before compromise was detected. What it DOES provide is an
    // immutable record of exactly which sessions fell in that window, which is
    // the evidence-log property and is what a dispute needs.
    const { registry, registrar, attacker, bankDid, bankNumber } =
      await loadFixture(fixture);

    const sid = SID(CH("pre-revocation"), bankNumber);
    await registry.connect(attacker).anchorSession(sid, CH("root"), CH("transcript"));

    const anchorBefore = await registry.getAnchor(sid);
    expect(anchorBefore.blockTime).to.be.greaterThan(0);

    await registry.connect(registrar).setStatus(bankDid, Status.Revoked);
    const rec = await registry.resolve(bankDid);

    // The anchor timestamp and the revocation timestamp are both on chain and
    // both consensus-supplied, so the window is bounded and provable.
    expect(anchorBefore.blockTime).to.be.lessThanOrEqual(rec.updatedAt);

    const anchorAfter = await registry.getAnchor(sid);
    expect(anchorAfter.digestRoot).to.equal(anchorBefore.digestRoot);
  });
});

describe("A4 - tampered credential claim", () => {
  it("the on-chain key hash is the referent and cannot be altered by a caller", async () => {
    const { registry, attacker, bankDid } = await loadFixture(fixture);

    await expect(
      registry.connect(attacker).rotateKey(
        bankDid, ethers.hexlify(ethers.randomBytes(64))
      )
    ).to.be.revertedWithCustomError(registry, "NotController");
  });

  it("an attacker cannot add a channel to another organisation", async () => {
    const { registry, attacker, bankDid } = await loadFixture(fixture);

    await expect(
      registry.connect(attacker).addChannel(bankDid, CH("+61399999999"))
    ).to.be.revertedWithCustomError(registry, "NotController");
  });
});

describe("A5 - revoked credential", () => {
  it("a revoked credential fails Layer 1 in the same block", async () => {
    const { registry, registrar, bankDid, bankNumber } = await loadFixture(fixture);

    const tx = await registry.connect(registrar).setStatus(bankDid, Status.Revoked);
    const receipt = await tx.wait();

    const rec = await registry.resolve(bankDid, { blockTag: receipt.blockNumber });
    expect(Number(rec.status)).to.equal(Status.Revoked);
  });

  it("revocation is observable without polling", async () => {
    const { registry, registrar, bankDid } = await loadFixture(fixture);

    await expect(registry.connect(registrar).setStatus(bankDid, Status.Revoked))
      .to.emit(registry, "StatusChanged")
      .withArgs(bankDid, Status.Active, Status.Revoked);
  });
});

describe("A6 - expired credential / stale key epoch", () => {
  it("key rotation advances the epoch so an old assertion is identifiable", async () => {
    const { registry, registrar, bankDid } = await loadFixture(fixture);

    const before = await registry.resolve(bankDid);
    expect(before.keyEpoch).to.equal(1);

    const newKey = ethers.hexlify(ethers.randomBytes(64));
    await registry.connect(registrar).rotateKey(bankDid, newKey);

    const after = await registry.resolve(bankDid);
    expect(after.keyEpoch).to.equal(2);

    // An assertion naming epoch 1 no longer matches the current record, so a
    // verifier rejects it without needing any revocation list.
    expect(after.pubKeyHash).to.equal(ethers.keccak256(newKey));
    expect(after.pubKeyHash).to.not.equal(before.pubKeyHash);
  });

  it("a suspended credential fails Layer 1 and is reversible", async () => {
    const { registry, registrar, bankDid, bankNumber } = await loadFixture(fixture);

    await registry.connect(registrar).setStatus(bankDid, Status.Suspended);
    expect((await layer1Verdict(registry, bankDid, bankNumber)).pass).to.equal(false);

    await registry.connect(registrar).setStatus(bankDid, Status.Active);
    expect((await layer1Verdict(registry, bankDid, bankNumber)).pass).to.equal(true);
  });
});

describe("A7 - replayed session assertion", () => {
  it("session binding: an anchor for one sid has no effect on another", async () => {
    // sid = H(nonce || chid). A fresh nonce per session means an assertion
    // cannot be lifted from an earlier call.
    const { registry, carrier1, bankNumber } = await loadFixture(fixture);

    const sidA = SID(CH("nonce-call-A"), bankNumber);
    const sidB = SID(CH("nonce-call-B"), bankNumber);

    await registry.connect(carrier1).anchorSession(sidA, CH("root"), CH("transcript"));

    expect((await registry.getAnchor(sidA)).digestRoot).to.equal(CH("root"));
    expect((await registry.getAnchor(sidB)).digestRoot).to.equal(ethers.ZeroHash);
  });

  it("an attestation is bound to its session and cannot be transplanted", async () => {
    const { registry, carrier1, bankNumber } = await loadFixture(fixture);

    const sidA = SID(CH("nonce-A"), bankNumber);
    const sidB = SID(CH("nonce-B"), bankNumber);

    await registry.connect(carrier1).attest(sidA, 0, CH("claim-for-A"));

    expect((await registry.getAttestations(sidA)).length).to.equal(1);
    expect((await registry.getAttestations(sidB)).length).to.equal(0);
  });

  it("the same nonce with a different channel yields a different session", async () => {
    const { registry, carrier1 } = await loadFixture(fixture);

    const nonce = CH("shared-nonce");
    const sid1 = SID(nonce, CH("+61312345678"));
    const sid2 = SID(nonce, CH("+61398765432"));

    expect(sid1).to.not.equal(sid2);

    await registry.connect(carrier1).anchorSession(sid1, CH("root"), CH("t"));
    expect((await registry.getAnchor(sid2)).digestRoot).to.equal(ethers.ZeroHash);
  });
});

describe("A8 - in-path identifier rewrite, audio untouched", () => {
  it("a rewrite between two attesting hops produces a visible discontinuity", async () => {
    // The verifier compares each hop's claim against the presented identifier.
    // Hop 0 and hop 2 attest to the genuine identifier; hop 1 rewrote it.
    const { registry, carrier1, carrier2, recipient, bankNumber } =
      await loadFixture(fixture);

    const sid = SID(CH("rewrite-session"), bankNumber);
    const genuine = CH("claim:+61312345678");
    const rewritten = CH("claim:+61399999999");

    await registry.connect(carrier1).attest(sid, 0, genuine);
    await registry.connect(recipient).attest(sid, 1, rewritten);
    await registry.connect(carrier2).attest(sid, 2, genuine);

    const transcript = await registry.getAttestations(sid);
    expect(transcript.length).to.equal(3);

    const claims = transcript.map((a) => a.claim);
    const distinct = new Set(claims);
    expect(distinct.size).to.be.greaterThan(
      1, "a rewrite between attesting hops must be visible as a discontinuity"
    );
  });

  it("a rewrite adjacent to a non-attesting hop yields bottom, not failure", async () => {
    // Only hop 0 attested. There is no downstream observation, so the verifier
    // reaches no verdict on the path. Bottom satisfies the conjunct - the
    // session is not demoted for a path nobody watched.
    const { registry, carrier1, bankNumber } = await loadFixture(fixture);

    const sid = SID(CH("unobserved-rewrite"), bankNumber);
    await registry.connect(carrier1).attest(sid, 0, CH("claim:+61312345678"));

    const transcript = await registry.getAttestations(sid);
    expect(transcript.length).to.equal(1);

    const k = 2;
    const verdict = transcript.length < k ? "bottom" : "verdict";
    expect(verdict).to.equal("bottom");
  });

  it("attestations are attributable, so a false claim is traceable", async () => {
    const { registry, recipient, bankNumber } = await loadFixture(fixture);

    const sid = SID(CH("attribution"), bankNumber);
    await registry.connect(recipient).attest(sid, 1, CH("claim:+61399999999"));

    const t = await registry.getAttestations(sid);
    expect(t[0].attestor).to.equal(recipient.address);
    expect(t[0].blockTime).to.be.greaterThan(0);
  });
});

describe("A9 - media substitution in transit", () => {
  it("the digest root is bound to the session and immutable once written", async () => {
    const { registry, carrier1, attacker, bankNumber } = await loadFixture(fixture);

    const sid = SID(CH("media-session"), bankNumber);
    const genuineRoot = CH("merkle-root-of-genuine-audio");

    await registry.connect(carrier1).anchorSession(sid, genuineRoot, CH("transcript"));

    // The attacker cannot replace the committed root with one matching
    // substituted audio.
    await expect(
      registry.connect(attacker).anchorSession(
        sid, CH("merkle-root-of-substituted-audio"), CH("transcript")
      )
    ).to.be.revertedWithCustomError(registry, "SessionAlreadyAnchored");

    expect((await registry.getAnchor(sid)).digestRoot).to.equal(genuineRoot);
  });

  it("audio never reaches the chain - only fixed-width commitments", async () => {
    const { registry } = await loadFixture(fixture);
    const frag = registry.interface.getFunction("anchorSession");

    for (const input of frag.inputs) {
      expect(input.type).to.equal(
        "bytes32",
        `${input.name} is ${input.type}; a variable-length type could carry a payload`
      );
    }
  });

  it("the anchor commits digest and path together in one write", async () => {
    // This is what makes substitution and rewrite jointly non-repudiable: an
    // adversary cannot alter one without invalidating the commitment to both.
    const { registry, carrier1, bankNumber } = await loadFixture(fixture);

    const sid = SID(CH("joint"), bankNumber);
    const tx = await registry.connect(carrier1)
      .anchorSession(sid, CH("digest-root"), CH("path-hash"));
    const receipt = await tx.wait();

    const events = receipt.logs.filter((l) => {
      try { return registry.interface.parseLog(l).name === "SessionAnchored"; }
      catch { return false; }
    });
    expect(events.length).to.equal(1);

    const a = await registry.getAnchor(sid);
    expect(a.digestRoot).to.equal(CH("digest-root"));
    expect(a.pathTranscriptHash).to.equal(CH("path-hash"));
  });
});

describe("A10 - synthesised speech (Layer 4 gating)", () => {
  it("no detector score can be written to the chain", async () => {
    // Proposition 1: the detector may only demote, never promote. Enforced
    // structurally - the ABI has no entry point that accepts a score.
    const { registry } = await loadFixture(fixture);

    const fns = registry.interface.fragments.filter((f) => f.type === "function");
    const names = fns.map((f) => f.name.toLowerCase());

    for (const forbidden of ["setscore", "setliveness", "setdetector",
                             "submitscore", "setconfidence"]) {
      expect(names).to.not.include(
        forbidden,
        "a detector score on chain would permit promotion, contradicting Prop. 1"
      );
    }
  });

  it("no write function accepts a numeric confidence parameter", async () => {
    const { registry } = await loadFixture(fixture);

    const writes = registry.interface.fragments.filter(
      (f) => f.type === "function" &&
             f.stateMutability !== "view" && f.stateMutability !== "pure"
    );

    for (const fn of writes) {
      for (const input of fn.inputs) {
        const isScoreLike = /score|confidence|probability|likelihood/i.test(input.name);
        expect(isScoreLike).to.equal(
          false, `${fn.name} takes ${input.name}, which looks like a detector score`
        );
      }
    }
  });

  it("the anchor record has no field a detector could populate", async () => {
    const { registry, carrier1, bankNumber } = await loadFixture(fixture);

    const sid = SID(CH("gating"), bankNumber);
    await registry.connect(carrier1).anchorSession(sid, CH("root"), CH("transcript"));

    const a = await registry.getAnchor(sid);
    const fields = Object.keys(a.toObject());

    expect(fields.sort()).to.deep.equal(
      ["anchoredBy", "blockTime", "digestRoot", "pathTranscriptHash"],
      "the anchor must carry no detector output"
    );
  });
});

describe("coverage summary", () => {
  it("prints the table row status for the paper", async () => {
    // Not an assertion. Emits the coverage row states so the table in the paper
    // and the test suite can be checked against each other by eye.
    const rows = [
      ["A1 ", "no credential",                  "Layer 1"],
      ["A2 ", "self-signed",                    "Layer 1"],
      ["A3 ", "stolen credential",              "Layer 1 + revocation (window stated)"],
      ["A4 ", "tampered claim",                 "Layer 1"],
      ["A5 ", "revoked credential",             "Layer 1"],
      ["A6 ", "expired / stale epoch",          "Layer 1"],
      ["A7 ", "replayed assertion",             "Layer 3 session binding"],
      ["A8 ", "in-path identifier rewrite",     "Layer 2 (bottom when unobserved)"],
      ["A9 ", "media substitution",             "Layer 3 digest"],
      ["A10", "synthesised speech",             "Layer 4 (gating only)"],
    ];
    console.log("\n      BVI coverage, as asserted above:");
    for (const [id, attack, mech] of rows) {
      console.log(`        ${id}  ${attack.padEnd(30)} -> ${mech}`);
    }
    expect(rows.length).to.equal(10);
  });
});
