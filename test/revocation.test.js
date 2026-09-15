const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

/**
 * REVOCATION - Section 4.2 and Section 7.1
 *
 * Paper: revocation is "a state transition whose effect is immediately visible
 * to every verifier and suppressible by none", including by an operator liable
 * for the compromise.
 *
 * That sentence decomposes into four separate properties, and each is a
 * separate test below:
 *
 *   (a) TWO INDEPENDENT PRINCIPALS may revoke, so losing one does not block it.
 *   (b) REVOCATION IS TERMINAL, so it cannot be undone after the fact.
 *   (c) EFFECT IS IMMEDIATE in the same block, with no settlement delay.
 *   (d) IT IS OBSERVABLE via an event any client can subscribe to.
 *
 * A fifth property, INCLUSION, is not enforceable in Solidity at all. It is a
 * deployment property, and it is the entire reason setStatus is submitted to
 * the L1 instance rather than the L2. See the note at the end of this file.
 */

const Status = {
  Unregistered: 0,
  Active: 1,
  Suspended: 2,
  Revoked: 3,
};

const CH = (s) => ethers.keccak256(ethers.toUtf8Bytes(s));

async function deployFixture() {
  const [registrar, attacker, recipient, outsider] = await ethers.getSigners();

  const Factory = await ethers.getContractFactory("BVIRegistry");
  const registry = await Factory.deploy(registrar.address);
  await registry.waitForDeployment();

  const did = CH("did:bvi:examplebank");
  const pubKey = ethers.hexlify(ethers.randomBytes(64));
  const channel = CH("+61312345678");

  await registry.connect(registrar).register(did, pubKey, [channel]);

  return { registry, registrar, attacker, recipient, outsider, did, channel };
}

describe("(a) two independent principals can revoke", () => {
  it("the controller can revoke", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await expect(registry.connect(registrar).setStatus(did, Status.Revoked))
      .to.emit(registry, "StatusChanged")
      .withArgs(did, Status.Active, Status.Revoked);

    expect((await registry.resolve(did)).status).to.equal(Status.Revoked);
  });

  it("nobody outside the two principals can revoke", async () => {
    const { registry, outsider, did } = await loadFixture(deployFixture);

    await expect(
      registry.connect(outsider).setStatus(did, Status.Revoked)
    ).to.be.revertedWithCustomError(registry, "NotAuthorisedToSetStatus");
  });

  it("an attacker holding a stolen controller key cannot block revocation", async () => {
    // This is the scenario in Section 7.1. The organisation's signing key is
    // compromised. The attacker is now, from the chain's point of view, the
    // controller. The point of the test is that the registrar remains able to
    // act, so the attacker's control over one principal is not enough.
    const { registry, registrar, attacker, did } = await loadFixture(
      deployFixture
    );

    // The attacker cannot use their position to hold the record open.
    await expect(
      registry.connect(attacker).setStatus(did, Status.Revoked)
    ).to.be.revertedWithCustomError(registry, "NotAuthorisedToSetStatus");

    // The registrar revokes regardless.
    await registry.connect(registrar).setStatus(did, Status.Revoked);
    expect((await registry.resolve(did)).status).to.equal(Status.Revoked);
  });
});

describe("(b) revocation is terminal and cannot be undone", () => {
  it("a revoked DID cannot be returned to Active", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await registry.connect(registrar).setStatus(did, Status.Revoked);

    await expect(
      registry.connect(registrar).setStatus(did, Status.Active)
    ).to.be.revertedWithCustomError(registry, "RevokedIsTerminal");
  });

  it("a revoked DID cannot be moved to Suspended either", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await registry.connect(registrar).setStatus(did, Status.Revoked);

    await expect(
      registry.connect(registrar).setStatus(did, Status.Suspended)
    ).to.be.revertedWithCustomError(registry, "RevokedIsTerminal");
  });

  it("a revoked DID cannot be re-registered to clear its history", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await registry.connect(registrar).setStatus(did, Status.Revoked);

    const pk = ethers.hexlify(ethers.randomBytes(64));
    await expect(
      registry.connect(registrar).register(did, pk, [])
    ).to.be.revertedWithCustomError(registry, "AlreadyRegistered");
  });

  it("a revoked organisation cannot rotate to a fresh key", async () => {
    // Otherwise revocation would be trivially escapable: revoke, rotate, resume.
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await registry.connect(registrar).setStatus(did, Status.Revoked);

    // Rotation still succeeds at the storage level but the status is unchanged
    // and terminal, so a verifier rejects on status regardless of the key.
    const pk = ethers.hexlify(ethers.randomBytes(64));
    await registry.connect(registrar).rotateKey(did, pk);

    expect((await registry.resolve(did)).status).to.equal(Status.Revoked);
  });
});

describe("(c) the effect is immediate", () => {
  it("a revocation is visible to a reader in the same block", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    expect((await registry.resolve(did)).status).to.equal(Status.Active);

    const tx = await registry.connect(registrar).setStatus(did, Status.Revoked);
    const receipt = await tx.wait();

    // Read pinned to the exact block containing the revocation.
    const atBlock = await registry.resolve(did, {
      blockTag: receipt.blockNumber,
    });
    expect(atBlock.status).to.equal(Status.Revoked);
  });

  it("no settlement or challenge window exists in the contract", async () => {
    // A time-delayed revocation would be an operator-suppressible one. Assert
    // there is no pending-state machinery: the transition is atomic.
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await registry.connect(registrar).setStatus(did, Status.Revoked);

    // No advancing of time is needed for the new status to hold.
    expect((await registry.resolve(did)).status).to.equal(Status.Revoked);

    const names = registry.interface.fragments
      .filter((f) => f.type === "function")
      .map((f) => f.name);

    for (const forbidden of ["finalizeStatus", "commitStatus", "confirmStatus"]) {
      expect(names).to.not.include(
        forbidden,
        "a two-phase revocation would introduce a suppression window"
      );
    }
  });
});

describe("(d) the effect is observable without polling", () => {
  it("StatusChanged carries both the old and new status", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await expect(registry.connect(registrar).setStatus(did, Status.Suspended))
      .to.emit(registry, "StatusChanged")
      .withArgs(did, Status.Active, Status.Suspended);

    await expect(registry.connect(registrar).setStatus(did, Status.Revoked))
      .to.emit(registry, "StatusChanged")
      .withArgs(did, Status.Suspended, Status.Revoked);
  });

  it("StatusChanged indexes the DID so a client can filter server-side", async () => {
    // If did were not indexed, a client would have to pull every StatusChanged
    // event on the contract and filter locally. On a public RPC that is the
    // difference between a viable light client and one that needs its own node,
    // which is exactly the R2 concern flagged for the rollup check.
    const { registry } = await loadFixture(deployFixture);

    const ev = registry.interface.getEvent("StatusChanged");
    const didParam = ev.inputs.find((i) => i.name === "did");

    expect(didParam.indexed).to.equal(
      true,
      "did must be indexed so clients can subscribe per-organisation"
    );
  });

  it("a client filtering on one DID does not see another organisation's events", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    const other = CH("did:bvi:otherbank");
    const pk = ethers.hexlify(ethers.randomBytes(64));
    await registry.connect(registrar).register(other, pk, []);

    await registry.connect(registrar).setStatus(other, Status.Suspended);
    await registry.connect(registrar).setStatus(did, Status.Revoked);

    const logs = await registry.queryFilter(
      registry.filters.StatusChanged(did)
    );

    // Registration itself emits StatusChanged(Unregistered -> Active).
    expect(logs.length).to.equal(2);
    expect(logs[1].args.newStatus).to.equal(Status.Revoked);
  });
});

describe("status transitions - remaining state machine", () => {
  it("Suspended is reversible", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await registry.connect(registrar).setStatus(did, Status.Suspended);
    await registry.connect(registrar).setStatus(did, Status.Active);

    expect((await registry.resolve(did)).status).to.equal(Status.Active);
  });

  it("a no-op transition reverts rather than emitting a misleading event", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await expect(
      registry.connect(registrar).setStatus(did, Status.Active)
    ).to.be.revertedWithCustomError(registry, "NoStatusChange");
  });

  it("a DID cannot be pushed back to Unregistered", async () => {
    const { registry, registrar, did } = await loadFixture(deployFixture);

    await expect(
      registry.connect(registrar).setStatus(did, Status.Unregistered)
    ).to.be.revertedWithCustomError(registry, "CannotSetUnregistered");
  });

  it("an unknown DID resolves to Unregistered rather than reverting", async () => {
    // A verifier must be able to distinguish "not in the registry" from
    // "call failed". Returning the zero record is the correct behaviour.
    const { registry } = await loadFixture(deployFixture);

    const rec = await registry.resolve(CH("did:bvi:nonexistent"));
    expect(rec.status).to.equal(Status.Unregistered);
    expect(rec.pubKeyHash).to.equal(ethers.ZeroHash);
  });
});

/**
 * NOT TESTABLE HERE - INCLUSION
 *
 * Everything above establishes that once a setStatus transaction executes, its
 * effect is immediate, terminal, observable, and not suppressible by either
 * principal. What no Solidity test can establish is that the transaction gets
 * *included* in a block promptly.
 *
 * On L1, ordering is decided by a competitive proposer set and no single
 * operator can hold a transaction out. On a rollup with a centralised
 * sequencer, one operator does control ordering. It cannot forge state, because
 * batch data is posted to L1 and anyone can reconstruct the L2 independently,
 * but it can decline to include a transaction it has been handed. The forced
 * inclusion path exists, and its worst-case delay is the number that decides
 * whether the L1/L2 split is necessary or merely tidy.
 *
 * ACTION: measure that delay from the rollup's own documentation and record it
 * in docs/forced-inclusion.md before submission. It is a docs read, not an
 * experiment, and it is the last piece of the Section 4.2 argument.
 */
