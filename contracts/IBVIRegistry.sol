// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.24;

/// @title IBVIRegistry
/// @notice On-ledger registry for BVI: organisational identity (Layer 1),
///         per-hop path attestation (Layer 2), and the per-session joint
///         anchor committing to the audio digest root and path transcript
///         (Layer 3).
/// @dev    Design constraints carried from the paper:
///         - Every call-time verifier interaction is a `view` read (R2, R9).
///           A recipient never needs an account and never pays gas.
///         - `isAuthorisedChannel` resolves in a single cold SLOAD via a
///           nested mapping (Section 5.1, "data-centric").
///         - `anchorSession` takes fixed-width arguments only, so per-session
///           cost is constant in call duration and in hop count.
///         - `setStatus` emits `StatusChanged` so clients can invalidate
///           cached records without polling.
interface IBVIRegistry {
    /// @notice Lifecycle state of a registered organisation.
    /// @dev Revoked is terminal. Suspended is reversible.
    enum Status {
        Unregistered, // 0 - default for an unknown DID
        Active,       // 1 - may originate verifiable sessions
        Suspended,    // 2 - temporarily withheld, reversible
        Revoked       // 3 - terminal; key compromise or deregistration
    }

    /// @notice Identity record for one organisation.
    /// @param pubKeyHash   keccak256 of the raw public key bytes. The full key
    ///                     is emitted in events and served off-chain; storing
    ///                     only the hash keeps `resolve` a fixed-size read.
    /// @param status       current lifecycle state
    /// @param keyEpoch     increments on every rotation; a session assertion
    ///                     names the epoch it was signed under, so an assertion
    ///                     cannot be replayed across a rotation
    /// @param registeredAt block timestamp of first registration
    /// @param updatedAt    block timestamp of the last mutation
    struct Record {
        bytes32 pubKeyHash;
        Status status;
        uint32 keyEpoch;
        uint64 registeredAt;
        uint64 updatedAt;
    }

    /// @notice One carrier's claim about the session at a given hop.
    /// @param attestor  address of the attesting carrier
    /// @param claim     keccak256 over (sid, hop, presented identifier,
    ///                  ingress, egress) as constructed by the client
    /// @param blockTime timestamp supplied by consensus, not by any party to
    ///                  a later dispute (R7)
    /// @param hop       position in the path, 0 = originating
    struct Attestation {
        address attestor;
        bytes32 claim;
        uint64 blockTime;
        uint8 hop;
    }

    /// @notice The single per-session commitment written at teardown.
    /// @param digestRoot         Merkle root over the robust digest sequence
    /// @param pathTranscriptHash keccak256 over the ordered attestation set
    /// @param anchoredBy         address that submitted the anchor
    /// @param blockTime          consensus timestamp
    struct Anchor {
        bytes32 digestRoot;
        bytes32 pathTranscriptHash;
        address anchoredBy;
        uint64 blockTime;
    }

    // ---------------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------------

    event Registered(bytes32 indexed did, bytes32 pubKeyHash, bytes pubKey);
    event KeyRotated(bytes32 indexed did, bytes32 newPubKeyHash, uint32 keyEpoch, bytes newPubKey);
    event ChannelAdded(bytes32 indexed did, bytes32 indexed channelHash);
    event ChannelRemoved(bytes32 indexed did, bytes32 indexed channelHash);

    /// @notice Emitted on every status transition. Clients subscribe to this to
    ///         invalidate cached identity records. Revocation visibility
    ///         (Section 4.2) rests on this event plus the L1 deployment.
    event StatusChanged(bytes32 indexed did, Status oldStatus, Status newStatus);

    event Attested(bytes32 indexed sid, uint8 indexed hop, address indexed attestor, bytes32 claim);
    event SessionAnchored(bytes32 indexed sid, bytes32 digestRoot, bytes32 pathTranscriptHash);

    // ---------------------------------------------------------------------
    // Layer 1 - identity (writes, amortised over an organisation's volume)
    // ---------------------------------------------------------------------

    function register(bytes32 did, bytes calldata pubKey, bytes32[] calldata channelHashes) external;

    function rotateKey(bytes32 did, bytes calldata newPubKey) external;

    function addChannel(bytes32 did, bytes32 channelHash) external;

    function removeChannel(bytes32 did, bytes32 channelHash) external;

    /// @dev Deployed to L1 in the split configuration. Inclusion of this call
    ///      must not be gateable by any single operator (Section 4.2).
    function setStatus(bytes32 did, Status newStatus) external;

    // ---------------------------------------------------------------------
    // Layer 2 - path (write, paid by carriers, optional)
    // ---------------------------------------------------------------------

    function attest(bytes32 sid, uint8 hop, bytes32 claim) external;

    // ---------------------------------------------------------------------
    // Layer 3 - joint anchor (the one per-session write)
    // ---------------------------------------------------------------------

    function anchorSession(bytes32 sid, bytes32 digestRoot, bytes32 pathTranscriptHash) external;

    // ---------------------------------------------------------------------
    // Reads - every call-time verifier interaction lives here
    // ---------------------------------------------------------------------

    function resolve(bytes32 did) external view returns (Record memory);

    function isAuthorisedChannel(bytes32 did, bytes32 channelHash) external view returns (bool);

    function getAttestations(bytes32 sid) external view returns (Attestation[] memory);

    function getAnchor(bytes32 sid) external view returns (Anchor memory);
}
