#!/usr/bin/env python3
"""
Analytical gas model for the BVI registry.

WHY THIS EXISTS

Two reasons, and the second is the important one.

First, this container has no solc, so the measured Table 1 has to be produced on
your machine. This model gives you the expected numbers now, and something to
check the measurement against when you run it. If Hardhat disagrees with this by
more than a few percent on any row, one of the two is wrong and it is worth
finding out which before the number goes in a paper.

Second, and more useful: a reviewer will ask *why* the anchor costs what it
costs, and "we measured it" is a weak answer. The breakdown below attributes
every gas unit to a specific cause, which lets you say the recurring per-session
cost is dominated by three cold SSTOREs and is therefore a property of the
storage layout rather than of the implementation.

COSTS USED (post-Berlin EIP-2929, post-Istanbul EIP-2028; `paris` EVM)

  intrinsic transaction              21000
  calldata zero byte                     4
  calldata non-zero byte                16
  SSTORE zero -> non-zero            20000  + cold slot surcharge
  SSTORE non-zero -> non-zero         2900  + cold slot surcharge
  cold storage slot access            2100
  warm storage slot access             100
  LOG base                             375
  LOG per topic                        375
  LOG per byte of data                   8
  KECCAK256 base                        30
  KECCAK256 per 32-byte word             6

These are protocol constants, not estimates. The uncertainty in this model is
in the "misc" term, which covers stack, memory and control flow the optimiser
may rearrange.
"""

from dataclasses import dataclass, field

INTRINSIC = 21000
CALLDATA_ZERO = 4
CALLDATA_NONZERO = 16
SSTORE_SET = 20000
SSTORE_RESET = 2900
COLD_SLOAD = 2100
WARM_ACCESS = 100
LOG_BASE = 375
LOG_TOPIC = 375
LOG_BYTE = 8
KECCAK_BASE = 30
KECCAK_WORD = 6


def calldata_cost(n_nonzero: int, n_zero: int) -> int:
    return n_nonzero * CALLDATA_NONZERO + n_zero * CALLDATA_ZERO


def keccak(n_bytes: int) -> int:
    return KECCAK_BASE + KECCAK_WORD * ((n_bytes + 31) // 32)


def mapping_slot(depth: int = 1) -> int:
    """Deriving a mapping slot is keccak256(key . slot), 64 bytes per level."""
    return depth * keccak(64)


def log_cost(n_topics: int, n_data_bytes: int) -> int:
    """n_topics includes the event signature topic for non-anonymous events."""
    return LOG_BASE + n_topics * LOG_TOPIC + n_data_bytes * LOG_BYTE


@dataclass
class Op:
    name: str
    layer: str
    items: list = field(default_factory=list)   # (label, gas)
    note: str = ""

    def total(self) -> int:
        return sum(g for _, g in self.items)

    def add(self, label, gas):
        self.items.append((label, int(gas)))
        return self


def model_anchor_session() -> Op:
    """anchorSession(bytes32 sid, bytes32 digestRoot, bytes32 pathTranscriptHash)

    THE RECURRING PER-SESSION COST. Everything else in the table is amortised.
    """
    op = Op("anchorSession", "L3",
            note="the only per-session write; constant in duration and hop count")
    op.add("intrinsic transaction", INTRINSIC)
    # 4-byte selector + three 32-byte words. Roots and hashes are effectively
    # random, so nearly every byte is non-zero. This is the pessimistic case and
    # the right one to quote.
    op.add("calldata (4 + 96 bytes, assume non-zero)", calldata_cost(100, 0))
    op.add("derive _anchors[sid] slot", mapping_slot(1))
    # Write-once guard reads the packed slot holding anchoredBy.
    op.add("SLOAD anchoredBy slot (cold, guard)", COLD_SLOAD)
    op.add("SSTORE digestRoot (cold, 0 -> non-zero)", SSTORE_SET + COLD_SLOAD)
    op.add("SSTORE pathTranscriptHash (cold, 0 -> non-zero)", SSTORE_SET + COLD_SLOAD)
    op.add("SSTORE anchoredBy|blockTime (warm, 0 -> non-zero)", SSTORE_SET + WARM_ACCESS)
    # SessionAnchored(bytes32 indexed sid, bytes32, bytes32): sig + 1 indexed
    op.add("LOG2 SessionAnchored (64 bytes data)", log_cost(2, 64))
    op.add("misc stack/memory/dispatch", 500)
    return op


def model_attest() -> Op:
    """attest(bytes32 sid, uint8 hop, bytes32 claim)"""
    op = Op("attest", "L2", note="per hop, paid by the carrier, optional")
    op.add("intrinsic transaction", INTRINSIC)
    op.add("calldata (4 + 96 bytes, hop word mostly zero)", calldata_cost(70, 30))
    op.add("derive _attestations[sid][hop] slot", mapping_slot(2))
    op.add("SLOAD attestor slot (cold, duplicate guard)", COLD_SLOAD)
    op.add("SSTORE attestor|blockTime|hop (warm, 0 -> non-zero)", SSTORE_SET + WARM_ACCESS)
    op.add("SSTORE claim (cold, 0 -> non-zero)", SSTORE_SET + COLD_SLOAD)
    op.add("derive _hops[sid] array slot", mapping_slot(1))
    op.add("SLOAD array length (cold)", COLD_SLOAD)
    op.add("SSTORE array length (warm)", SSTORE_RESET + WARM_ACCESS)
    op.add("SSTORE array element (cold, 0 -> non-zero)", SSTORE_SET + COLD_SLOAD)
    op.add("keccak for array data slot", keccak(32))
    # Attested(bytes32 indexed, uint8 indexed, address indexed, bytes32)
    op.add("LOG4 Attested (32 bytes data)", log_cost(4, 32))
    op.add("misc stack/memory/dispatch", 600)
    return op


def model_set_status(first_transition: bool = True) -> Op:
    """setStatus(bytes32 did, Status newStatus)

    Cheap, because the status field shares a slot that registration already
    made non-zero. The revocation write is a 2900 reset, not a 20000 set.
    """
    op = Op("setStatus", "L1", note="submitted to the L1 instance; see Section 4.2")
    op.add("intrinsic transaction", INTRINSIC)
    op.add("calldata (4 + 64 bytes, status word mostly zero)", calldata_cost(40, 28))
    op.add("derive _records[did] slot", mapping_slot(1))
    op.add("SLOAD packed status slot (cold)", COLD_SLOAD)
    op.add("derive _controllers[did] slot", mapping_slot(1))
    op.add("SLOAD controller (cold, authorisation)", COLD_SLOAD)
    op.add("SSTORE packed status|updatedAt (warm, non-zero -> non-zero)",
           SSTORE_RESET + WARM_ACCESS)
    op.add("LOG2 StatusChanged (64 bytes data)", log_cost(2, 64))
    op.add("misc stack/memory/dispatch", 500)
    return op


def model_add_channel() -> Op:
    op = Op("addChannel", "L1", note="per channel")
    op.add("intrinsic transaction", INTRINSIC)
    op.add("calldata (4 + 64 bytes)", calldata_cost(68, 0))
    op.add("derive _records[did] slot", mapping_slot(1))
    op.add("SLOAD status (cold, existence check)", COLD_SLOAD)
    op.add("derive _controllers[did] slot", mapping_slot(1))
    op.add("SLOAD controller (cold)", COLD_SLOAD)
    op.add("derive _channels[did][ch] slot", mapping_slot(2))
    op.add("SLOAD channel (cold, duplicate guard)", COLD_SLOAD)
    op.add("SSTORE channel (warm, 0 -> non-zero)", SSTORE_SET + WARM_ACCESS)
    op.add("SSTORE updatedAt (warm, non-zero -> non-zero)", SSTORE_RESET + WARM_ACCESS)
    op.add("LOG3 ChannelAdded (no data)", log_cost(3, 0))
    op.add("misc stack/memory/dispatch", 500)
    return op


def model_register(n_channels: int = 1, pubkey_bytes: int = 64) -> Op:
    op = Op(f"register ({n_channels} channel{'s' if n_channels != 1 else ''})", "L1",
            note="per organisation, once")
    op.add("intrinsic transaction", INTRINSIC)
    # selector + did + offset + offset + key len + key + array len + hashes
    cd = 4 + 32 * 5 + pubkey_bytes + 32 * n_channels
    op.add(f"calldata ({cd} bytes)", calldata_cost(int(cd * 0.85), int(cd * 0.15)))
    op.add("keccak256(pubKey)", keccak(pubkey_bytes))
    op.add("derive _records[did] slot", mapping_slot(1))
    op.add("SLOAD status (cold, already-registered guard)", COLD_SLOAD)
    op.add("SSTORE pubKeyHash (cold, 0 -> non-zero)", SSTORE_SET + COLD_SLOAD)
    op.add("SSTORE packed status|epoch|times (warm, 0 -> non-zero)",
           SSTORE_SET + WARM_ACCESS)
    op.add("derive + SSTORE _controllers[did] (cold, 0 -> non-zero)",
           mapping_slot(1) + SSTORE_SET + COLD_SLOAD)
    for i in range(n_channels):
        op.add(f"channel {i}: derive + SLOAD + SSTORE (cold)",
               mapping_slot(2) + COLD_SLOAD + SSTORE_SET + WARM_ACCESS)
        op.add(f"channel {i}: LOG3 ChannelAdded", log_cost(3, 0))
    op.add("LOG2 Registered (key + hash as data)",
           log_cost(2, 32 + 64 + pubkey_bytes))
    op.add("LOG2 StatusChanged (64 bytes data)", log_cost(2, 64))
    op.add("misc stack/memory/loop/dispatch", 1500)
    return op


def model_read_is_authorised() -> Op:
    """A view call. Charged to nobody at call time; shown for completeness."""
    op = Op("isAuthorisedChannel (view)", "read",
            note="one cold SLOAD; recipient pays nothing")
    op.add("derive _channels[did][ch] slot", mapping_slot(2))
    op.add("SLOAD (cold)", COLD_SLOAD)
    op.add("misc", 150)
    return op


def main():
    ops = [
        model_register(1),
        model_register(4),
        model_add_channel(),
        model_set_status(),
        model_attest(),
        model_anchor_session(),
        model_read_is_authorised(),
    ]

    print("=" * 88)
    print("ANALYTICAL GAS MODEL - predicted Table 1")
    print("=" * 88)
    print("Derived from EVM opcode costs (EIP-2929/2028, `paris`). Compare against")
    print("the measured figures from `npm run gas`. Agreement within a few percent")
    print("validates both; a large gap means one of them is wrong.")
    print()
    print(f"{'Layer':<6} {'Operation':<28} {'Predicted gas':>14}   Notes")
    print("-" * 88)
    for op in ops:
        print(f"{op.layer:<6} {op.name:<28} {op.total():>14,}   {op.note}")
    print("-" * 88)

    anchor = model_anchor_session()
    print("\nWHERE THE PER-SESSION GAS GOES  (anchorSession)")
    print("-" * 88)
    total = anchor.total()
    for label, g in sorted(anchor.items, key=lambda x: -x[1]):
        print(f"  {label:<52} {g:>8,}  {g/total*100:>5.1f}%")
    print("-" * 88)
    print(f"  {'TOTAL':<52} {total:>8,}")
    print()
    storage = sum(g for l, g in anchor.items if "SSTORE" in l)
    print(f"Storage writes are {storage:,} gas, {storage/total*100:.0f}% of the total.")
    print("The recurring cost is therefore a property of the storage layout - three")
    print("cold slots - rather than of the implementation. Nothing in the function")
    print("body varies with call duration or hop count, which is the constant-cost")
    print("claim restated at the opcode level.")
    print()

    print("COST AT NATIONAL CALL VOLUME")
    print("-" * 88)
    print("Per-session cost is anchorSession only. Illustrative gas prices; substitute")
    print("live figures before publication.")
    print()
    calls_per_year = 12_000_000_000    # order of magnitude for a national network
    eth_price_usd = 3000
    print(f"{'Deployment':<22} {'gas price':>12} {'per call':>14} "
          f"{'per 1M calls':>15} {'per year (12B)':>18}")
    print("-" * 88)
    for label, gwei in (("Ethereum L1", 20.0), ("Ethereum L1 (busy)", 60.0),
                        ("L2 rollup", 0.01), ("L2 rollup (busy)", 0.05)):
        eth = total * gwei * 1e-9
        usd = eth * eth_price_usd
        print(f"{label:<22} {gwei:>9.2f} gwei {'$' + format(usd, '.6f'):>14} "
              f"{'$' + format(usd * 1e6, ',.0f'):>15} "
              f"{'$' + format(usd * calls_per_year, ',.0f'):>18}")
    print("-" * 88)
    print("This is the calculation that rules out L1 as the anchor target and the")
    print("reason the deployment splits. Revocation still goes to L1, because it is")
    print("rare and because inclusion there cannot be gated by one operator.")
    print("=" * 88)


if __name__ == "__main__":
    main()
