// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.24;

import {IBVIRegistry} from "./IBVIRegistry.sol";

/// @title BVIRegistry
/// @notice Reference implementation of the BVI on-ledger registry.
///
/// @dev STORAGE LAYOUT NOTES (these decide the numbers in Table 1)
///
///  Record packs into 2 slots:
///    slot 0: pubKeyHash                                        (256 bits)
///    slot 1: status(8) | keyEpoch(32) | registeredAt(64) | updatedAt(64)
///                                                             (168 bits, packed)
///
///  Attestation packs into 2 slots:
///    slot 0: attestor(160) | blockTime(64) | hop(8)            (232 bits, packed)
///    slot 1: claim                                             (256 bits)
///
///  Anchor packs into 3 slots:
///    slot 0: digestRoot
///    slot 1: pathTranscriptHash
///    slot 2: anchoredBy(160) | blockTime(64)                   (224 bits, packed)
///
///  `_channels` is a nested mapping, so `isAuthorisedChannel` is exactly one
///  cold SLOAD (2100 gas) plus two keccak256 for slot derivation. This is the
///  "data-centric" property claimed in Section 5.1 and it is asserted by test.
///
/// @dev DEPLOYMENT
///  The same bytecode is deployed twice in the recommended configuration:
///    - L1 instance:  authoritative for identity and status. `setStatus` is
///                    submitted here so no rollup sequencer can gate inclusion.
///    - L2 instance:  carries `attest` and `anchorSession`, the per-session
///                    traffic, where write cost is amortised across a batch.
///  The client reads identity/status from L1 and path/anchor from L2. No code
///  differs between the two; only the client's endpoint configuration does.
contract BVIRegistry is IBVIRegistry {
    // ---------------------------------------------------------------------
    // Errors
    // ---------------------------------------------------------------------

    error NotRegistrar();
    error NotController();
    error NotAuthorisedToSetStatus();
    error AlreadyRegistered();
    error UnknownDid();
    error RevokedIsTerminal();
    error CannotSetUnregistered();
    error NoStatusChange();
    error EmptyPublicKey();
    error ZeroDid();
    error ZeroSession();
    error HopAlreadyAttested();
    error HopOutOfRange();
    error SessionAlreadyAnchored();
    error ChannelAlreadyAuthorised();
    error ChannelNotAuthorised();
    error TooManyChannels();

    // ---------------------------------------------------------------------
    // Constants
    // ---------------------------------------------------------------------

    /// @notice Upper bound on hops recorded per session. Bounds the gas of
    ///         `getAttestations` so an unbounded loop can never brick a read.
    ///         32 is comfortably above observed international call path depth.
    uint8 public constant MAX_HOPS = 32;

    /// @notice Upper bound on channels registered in a single `register` call.
    ///         Additional channels go through `addChannel`.
    uint256 public constant MAX_CHANNELS_PER_REGISTER = 16;

    // ---------------------------------------------------------------------
    // Storage
    // ---------------------------------------------------------------------

    /// @notice Address permitted to onboard new organisations and to revoke.
    /// @dev In deployment this is an accreditation body, not a carrier. It can
    ///      revoke but cannot un-revoke, cannot rotate an org's key, and cannot
    ///      alter an anchor. See `setStatus` for the suppression argument.
    address public immutable registrar;

    mapping(bytes32 did => Record) private _records;
    mapping(bytes32 did => address) private _controllers;

    /// @dev Nested mapping. One cold SLOAD answers a membership test.
    mapping(bytes32 did => mapping(bytes32 channelHash => bool)) private _channels;

    mapping(bytes32 sid => mapping(uint8 hop => Attestation)) private _attestations;
    mapping(bytes32 sid => uint8[]) private _hops;
    mapping(bytes32 sid => Anchor) private _anchors;

    // ---------------------------------------------------------------------
    // Construction
    // ---------------------------------------------------------------------

    constructor(address registrar_) {
        registrar = registrar_;
    }

    // ---------------------------------------------------------------------
    // Layer 1 - identity
    // ---------------------------------------------------------------------

    /// @inheritdoc IBVIRegistry
    /// @dev The caller becomes the controller. `pubKey` is emitted, not stored;
    ///      only its hash is retained so `resolve` stays a fixed 2-slot read.
    function register(
        bytes32 did,
        bytes calldata pubKey,
        bytes32[] calldata channelHashes
    ) external override {
        if (msg.sender != registrar) revert NotRegistrar();
        if (did == bytes32(0)) revert ZeroDid();
        if (pubKey.length == 0) revert EmptyPublicKey();
        if (_records[did].status != Status.Unregistered) revert AlreadyRegistered();
        if (channelHashes.length > MAX_CHANNELS_PER_REGISTER) revert TooManyChannels();

        bytes32 pkh = keccak256(pubKey);

        _records[did] = Record({
            pubKeyHash: pkh,
            status: Status.Active,
            keyEpoch: 1,
            registeredAt: uint64(block.timestamp),
            updatedAt: uint64(block.timestamp)
        });
        _controllers[did] = msg.sender;

        uint256 n = channelHashes.length;
        for (uint256 i = 0; i < n; ++i) {
            bytes32 ch = channelHashes[i];
            if (!_channels[did][ch]) {
                _channels[did][ch] = true;
                emit ChannelAdded(did, ch);
            }
        }

        emit Registered(did, pkh, pubKey);
        emit StatusChanged(did, Status.Unregistered, Status.Active);
    }

    /// @inheritdoc IBVIRegistry
    /// @dev Bumps `keyEpoch`. A session assertion names the epoch it was signed
    ///      under, so assertions do not survive a rotation.
    function rotateKey(bytes32 did, bytes calldata newPubKey) external override {
        Record storage r = _requireKnown(did);
        if (msg.sender != _controllers[did]) revert NotController();
        if (newPubKey.length == 0) revert EmptyPublicKey();

        bytes32 pkh = keccak256(newPubKey);
        uint32 epoch = r.keyEpoch + 1;

        r.pubKeyHash = pkh;
        r.keyEpoch = epoch;
        r.updatedAt = uint64(block.timestamp);

        emit KeyRotated(did, pkh, epoch, newPubKey);
    }

    /// @inheritdoc IBVIRegistry
    function addChannel(bytes32 did, bytes32 channelHash) external override {
        _requireKnown(did);
        if (msg.sender != _controllers[did]) revert NotController();
        if (_channels[did][channelHash]) revert ChannelAlreadyAuthorised();

        _channels[did][channelHash] = true;
        _records[did].updatedAt = uint64(block.timestamp);

        emit ChannelAdded(did, channelHash);
    }

    /// @inheritdoc IBVIRegistry
    function removeChannel(bytes32 did, bytes32 channelHash) external override {
        _requireKnown(did);
        if (msg.sender != _controllers[did]) revert NotController();
        if (!_channels[did][channelHash]) revert ChannelNotAuthorised();

        _channels[did][channelHash] = false;
        _records[did].updatedAt = uint64(block.timestamp);

        emit ChannelRemoved(did, channelHash);
    }

    /// @inheritdoc IBVIRegistry
    /// @dev SUPPRESSION ARGUMENT (Section 4.2, Section 7.1).
    ///
    ///      Two independent principals may revoke: the organisation's own
    ///      controller and the registrar. An attacker holding a stolen
    ///      controller key therefore cannot prevent revocation, because the
    ///      registrar can still act. A captured or negligent registrar cannot
    ///      prevent it either, because the controller can still act.
    ///
    ///      `Revoked` is terminal and enforced on-chain. Neither principal can
    ///      undo a revocation, so neither can suppress one after the fact.
    ///
    ///      What this function cannot do by itself is guarantee *inclusion*.
    ///      That is why it is submitted to the L1 instance: a rollup sequencer
    ///      controls ordering and could delay a transaction it holds. On L1 no
    ///      single operator gates inclusion.
    function setStatus(bytes32 did, Status newStatus) external override {
        Record storage r = _requireKnown(did);

        if (msg.sender != _controllers[did] && msg.sender != registrar) {
            revert NotAuthorisedToSetStatus();
        }
        if (newStatus == Status.Unregistered) revert CannotSetUnregistered();

        Status old = r.status;
        if (old == Status.Revoked) revert RevokedIsTerminal();
        if (old == newStatus) revert NoStatusChange();

        r.status = newStatus;
        r.updatedAt = uint64(block.timestamp);

        emit StatusChanged(did, old, newStatus);
    }

    // ---------------------------------------------------------------------
    // Layer 2 - path attestation
    // ---------------------------------------------------------------------

    /// @inheritdoc IBVIRegistry
    /// @dev Permissionless by design: requiring carrier accreditation before an
    ///      attestation counts would reintroduce the participation threshold
    ///      the paper's first claim removes.
    ///
    ///      First-writer-wins per (sid, hop). An adversary can squat a hop it
    ///      does not occupy, but `sid = H(nonce || chid)` is unpredictable
    ///      before setup and short-lived, so squatting requires being on-path
    ///      or racing a live session. A squatted hop with a false claim scores
    ///      0 (inconsistent) rather than 1, which is a detection outcome, not a
    ///      bypass. It does create a nuisance-demotion vector; the false-positive
    ///      cost of that is quantified in the RQ3 sweep.
    function attest(bytes32 sid, uint8 hop, bytes32 claim) external override {
        if (sid == bytes32(0)) revert ZeroSession();
        if (hop >= MAX_HOPS) revert HopOutOfRange();
        if (_attestations[sid][hop].attestor != address(0)) revert HopAlreadyAttested();

        _attestations[sid][hop] = Attestation({
            attestor: msg.sender,
            claim: claim,
            blockTime: uint64(block.timestamp),
            hop: hop
        });
        _hops[sid].push(hop);

        emit Attested(sid, hop, msg.sender, claim);
    }

    // ---------------------------------------------------------------------
    // Layer 3 - joint anchor
    // ---------------------------------------------------------------------

    /// @inheritdoc IBVIRegistry
    /// @dev THE CONSTANT-COST CLAIM.
    ///      Both arguments are fixed-width `bytes32`. `digestRoot` is a Merkle
    ///      root over the whole digest sequence, so a 10-second call and a
    ///      50-minute call commit the same 32 bytes. `pathTranscriptHash` is a
    ///      hash over the ordered attestation set, so a 2-hop and a 12-hop path
    ///      commit the same 32 bytes. Gas is therefore independent of both.
    ///      This is asserted directly in test/anchor.constant-cost.test.js.
    ///
    ///      Write-once. An anchor that could be rewritten would defeat the
    ///      post-hoc non-repudiation argument in Section 7.1.
    function anchorSession(
        bytes32 sid,
        bytes32 digestRoot,
        bytes32 pathTranscriptHash
    ) external override {
        if (sid == bytes32(0)) revert ZeroSession();
        if (_anchors[sid].anchoredBy != address(0)) revert SessionAlreadyAnchored();

        _anchors[sid] = Anchor({
            digestRoot: digestRoot,
            pathTranscriptHash: pathTranscriptHash,
            anchoredBy: msg.sender,
            blockTime: uint64(block.timestamp)
        });

        emit SessionAnchored(sid, digestRoot, pathTranscriptHash);
    }

    // ---------------------------------------------------------------------
    // Reads - no gas for the recipient, no account required
    // ---------------------------------------------------------------------

    /// @inheritdoc IBVIRegistry
    function resolve(bytes32 did) external view override returns (Record memory) {
        return _records[did];
    }

    /// @inheritdoc IBVIRegistry
    /// @dev Exactly one cold SLOAD. This is the single storage read claimed in
    ///      Section 5.1 and it is what keeps identity verification inside the
    ///      call-setup budget (R9).
    function isAuthorisedChannel(
        bytes32 did,
        bytes32 channelHash
    ) external view override returns (bool) {
        return _channels[did][channelHash];
    }

    /// @inheritdoc IBVIRegistry
    /// @dev Returns the transcript in hop order, ascending, regardless of the
    ///      order in which carriers wrote. Bounded by MAX_HOPS.
    function getAttestations(
        bytes32 sid
    ) external view override returns (Attestation[] memory) {
        uint8[] storage hops = _hops[sid];
        uint256 n = hops.length;
        Attestation[] memory out = new Attestation[](n);

        for (uint256 i = 0; i < n; ++i) {
            out[i] = _attestations[sid][hops[i]];
        }

        // Insertion sort by hop. n <= MAX_HOPS = 32, and this is a view call,
        // so the quadratic term is irrelevant and costs the caller nothing.
        for (uint256 i = 1; i < n; ++i) {
            Attestation memory key = out[i];
            uint256 j = i;
            while (j > 0 && out[j - 1].hop > key.hop) {
                out[j] = out[j - 1];
                --j;
            }
            out[j] = key;
        }

        return out;
    }

    /// @inheritdoc IBVIRegistry
    function getAnchor(bytes32 sid) external view override returns (Anchor memory) {
        return _anchors[sid];
    }

    /// @notice Controller address for a DID. Not part of IBVIRegistry; exposed
    ///         for clients that want to display the responsible principal.
    function controllerOf(bytes32 did) external view returns (address) {
        return _controllers[did];
    }

    /// @notice Number of hops that have attested to a session.
    function attestationCount(bytes32 sid) external view returns (uint256) {
        return _hops[sid].length;
    }

    // ---------------------------------------------------------------------
    // Internal
    // ---------------------------------------------------------------------

    function _requireKnown(bytes32 did) private view returns (Record storage r) {
        r = _records[did];
        if (r.status == Status.Unregistered) revert UnknownDid();
    }
}
