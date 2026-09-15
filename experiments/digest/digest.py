"""
Robust speech digest for BVI Layer 3.

No learned component. The construction is the Haitsma-Kalker style sub-band
energy-difference hash used by AuthentiCall, restated here with every parameter
exposed, because the parameter choice *is* the T4 decision.

    bit(n, m) = 1 if  [E(n,m) - E(n,m+1)] - [E(n-1,m) - E(n-1,m+1)] > 0
                0 otherwise

The double difference is what makes it robust. Differencing across bands
cancels any filter applied uniformly to the spectrum (a codec's shaping, a
handset's response). Differencing across time cancels slowly varying gain (AGC,
volume). What survives is the sign of the local spectro-temporal gradient,
which is a property of the speech itself.

BIT RATE, which is the whole of T4:

    bits_per_frame = n_bands - 1
    frames_per_second = fs / hop_samples
    bit_rate = bits_per_frame * frames_per_second

The digest must be carried to the recipient inside the signalling or media
path, in real time, alongside the call. If the side channel cannot sustain
bit_rate, Layer 3 does not work as described. See sidechannel.py for the
capacity comparison.
"""

from dataclasses import dataclass, asdict
import numpy as np


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DigestParams:
    """One full specification of the digest. This is what T4 has to fix."""

    fs: int = 8000                # narrowband telephony
    frame_ms: float = 32.0        # analysis window
    hop_ms: float = 20.0          # advance between frames
    n_bands: int = 17             # Bark-spaced filterbank -> 16 bits/frame
    f_lo: float = 300.0           # telephony passband lower edge
    f_hi: float = 3400.0          # telephony passband upper edge
    pre_emphasis: float = 0.97    # tilts the spectrum before analysis

    @property
    def frame_samples(self) -> int:
        return int(round(self.frame_ms * self.fs / 1000.0))

    @property
    def hop_samples(self) -> int:
        return int(round(self.hop_ms * self.fs / 1000.0))

    @property
    def bits_per_frame(self) -> int:
        return self.n_bands - 1

    @property
    def frames_per_second(self) -> float:
        return self.fs / self.hop_samples

    @property
    def bit_rate(self) -> float:
        """Bits per second the side channel must sustain. The T4 number."""
        return self.bits_per_frame * self.frames_per_second

    @property
    def bytes_per_second(self) -> float:
        return self.bit_rate / 8.0

    def label(self) -> str:
        return (f"{self.n_bands}b/{self.hop_ms:g}ms "
                f"({self.bits_per_frame} bits/frame, {self.bit_rate:.0f} bps)")

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(
            frame_samples=self.frame_samples,
            hop_samples=self.hop_samples,
            bits_per_frame=self.bits_per_frame,
            frames_per_second=self.frames_per_second,
            bit_rate_bps=self.bit_rate,
            bytes_per_second=self.bytes_per_second,
        )
        return d


# ---------------------------------------------------------------------------
# Filterbank
# ---------------------------------------------------------------------------

def hz_to_bark(f):
    """Traunmuller's Bark scale. Band edges follow perceptual spacing, which is
    where speech energy is actually distributed."""
    f = np.asarray(f, dtype=float)
    return (26.81 * f) / (1960.0 + f) - 0.53


def bark_to_hz(b):
    b = np.asarray(b, dtype=float)
    return 1960.0 * (b + 0.53) / (26.28 - b)


def band_edges(p: DigestParams) -> np.ndarray:
    """n_bands+1 edges, equally spaced on the Bark scale between f_lo and f_hi."""
    b_lo, b_hi = hz_to_bark(p.f_lo), hz_to_bark(p.f_hi)
    return bark_to_hz(np.linspace(b_lo, b_hi, p.n_bands + 1))


def filterbank_matrix(p: DigestParams, n_fft: int) -> np.ndarray:
    """(n_bands, n_fft//2+1) matrix of triangular band weights.

    Precomputed once; applying it is a single matmul per frame, which is what
    makes the digest cheap enough to run live on a handset.
    """
    edges = band_edges(p)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / p.fs)
    fb = np.zeros((p.n_bands, len(freqs)))

    for m in range(p.n_bands):
        lo, hi = edges[m], edges[m + 1]
        centre = 0.5 * (lo + hi)
        rising = (freqs >= lo) & (freqs <= centre)
        falling = (freqs > centre) & (freqs <= hi)
        if centre > lo:
            fb[m, rising] = (freqs[rising] - lo) / (centre - lo)
        if hi > centre:
            fb[m, falling] = (hi - freqs[falling]) / (hi - centre)

        s = fb[m].sum()
        if s > 0:
            fb[m] /= s          # area-normalised, so band width does not bias energy
        else:
            # Band narrower than one FFT bin. Fall back to the nearest bin so the
            # band still contributes rather than silently emitting a constant.
            fb[m, np.argmin(np.abs(freqs - centre))] = 1.0

    return fb


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

def band_energies(x: np.ndarray, p: DigestParams) -> np.ndarray:
    """(n_frames, n_bands) log band energies."""
    x = np.asarray(x, dtype=float)

    if p.pre_emphasis:
        x = np.append(x[0], x[1:] - p.pre_emphasis * x[:-1])

    L, H = p.frame_samples, p.hop_samples
    if len(x) < L:
        x = np.pad(x, (0, L - len(x)))

    n_frames = 1 + (len(x) - L) // H
    if n_frames < 1:
        return np.zeros((0, p.n_bands))

    idx = np.arange(L)[None, :] + H * np.arange(n_frames)[:, None]
    frames = x[idx] * np.hanning(L)[None, :]

    n_fft = 1 << int(np.ceil(np.log2(L)))
    spec = np.abs(np.fft.rfft(frames, n=n_fft, axis=1)) ** 2

    fb = filterbank_matrix(p, n_fft)
    energies = spec @ fb.T

    return np.log(energies + 1e-12)


def digest_bits(x: np.ndarray, p: DigestParams) -> np.ndarray:
    """(n_frames-1, bits_per_frame) uint8 bit matrix.

    The first frame produces no bits because the construction differences
    against the previous frame.
    """
    E = band_energies(x, p)
    if E.shape[0] < 2:
        return np.zeros((0, p.bits_per_frame), dtype=np.uint8)

    d_band = np.diff(E, axis=1)          # E(n,m) - E(n,m+1), across bands
    d_time = np.diff(d_band, axis=0)     # then across time
    return (d_time > 0).astype(np.uint8)


def ber(a: np.ndarray, b: np.ndarray) -> float:
    """Bit error rate over the overlapping frames.

    Truncating to the shorter of the two is deliberate. Packet loss and jitter
    change the received length, and a comparison that failed on a length
    mismatch would reject benign transmission rather than detecting substitution.
    """
    n = min(len(a), len(b))
    if n == 0:
        return 0.5     # no evidence either way; chance level
    return float(np.mean(a[:n] != b[:n]))


def ber_best_alignment(a: np.ndarray, b: np.ndarray, max_shift: int = 3) -> float:
    """BER minimised over a small frame offset.

    Jitter and codec delay shift the received stream by a fraction of a frame,
    which the plain BER would read as near-chance. A real verifier resynchronises
    over a few frames. `max_shift` frames at 20 ms is a 60 ms search window,
    which is the right order for telephony jitter buffers.
    """
    best = 1.0
    for s in range(-max_shift, max_shift + 1):
        if s >= 0:
            best = min(best, ber(a[s:], b))
        else:
            best = min(best, ber(a, b[-s:]))
    return best


# ---------------------------------------------------------------------------
# Activity gating
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS
#
# The construction takes the sign of a local spectro-temporal gradient. In a
# pause, every band energy sits on the numerical floor, the gradient is
# essentially zero, and the sign is decided by rounding rather than by content.
# Any perturbation - a codec's quantisation floor, a few dB of line noise -
# re-randomises those bits.
#
# Measured on the pipeline, this is not a marginal effect. With no gating, plain
# G.711 mu-law pushes whole-call BER to roughly 0.31 and 20 dB SNR noise to
# roughly 0.45, which is chance. A verifier using an ungated whole-call BER
# would reject essentially every real call.
#
# The fix is to compare only over frames that carry speech. This is not a
# convenience: a silent frame contains no content to authenticate, so including
# it in the comparison adds noise to the score and nothing else. The gate is
# computed by each endpoint from the audio it has, so it costs no extra bits on
# the side channel.
#
# It does not help an adversary. Substituted audio is also speech, so it is also
# active, and the comparison still runs over it.

def frame_energy(x: np.ndarray, p: DigestParams) -> np.ndarray:
    """Broadband log energy per analysis frame, aligned with band_energies."""
    E = band_energies(x, p)
    if E.shape[0] == 0:
        return np.zeros(0)
    # Sum in the linear domain, back to log. Mean of logs would let one dead
    # band drag an otherwise active frame below the gate.
    return np.log(np.exp(E).sum(axis=1) + 1e-12)


def activity_mask(x: np.ndarray, p: DigestParams,
                  rel_floor_db: float = 45.0) -> np.ndarray:
    """Boolean mask over BIT ROWS marking frames that carry speech.

    A frame is active when its energy is within `rel_floor_db` of the loudest
    frame in the utterance. Relative rather than absolute, so the gate does not
    move with the call's overall level.

    A bit row is the difference of frames n-1 and n, so it is active only when
    BOTH contributing frames are.
    """
    e = frame_energy(x, p)
    if len(e) < 2:
        return np.zeros(max(0, len(e) - 1), dtype=bool)

    thresh = e.max() - rel_floor_db * np.log(10) / 10.0
    active = e > thresh
    return active[1:] & active[:-1]


def ber_gated(a: np.ndarray, b: np.ndarray, mask: np.ndarray,
              min_frames: int = 10) -> float:
    """BER over active frames only, or NaN when there is nothing to compare.

    NaN is ABSTENTION, not a score. It means the segment held too little speech
    to support any verdict, and it must never be folded into a score
    distribution as though it were a measured BER. Doing so is what produced a
    degenerate 100 percent EER in the first run of this pipeline: the sentinel
    appeared in both the benign and the adversarial distribution and swamped the
    real separation.

    This makes Layer 3 ternary in exactly the way Layer 2 already is:

        BER <= tau     -> 1, consistent
        BER >  tau     -> 0, inconsistent
        NaN            -> bottom, insufficient evidence

    And bottom satisfies the conjunct, for the same reason it does at Layer 2:
    silence is not evidence of substitution. A caller who says nothing for two
    seconds must not be demoted for it.
    """
    n = min(len(a), len(b), len(mask))
    if n == 0:
        return float("nan")
    m = mask[:n]
    if m.sum() < min_frames:
        return float("nan")
    return float(np.mean(a[:n][m] != b[:n][m]))


def align_and_compare(ref_x: np.ndarray, recv_x: np.ndarray, p: DigestParams,
                      max_shift_ms: float = 25.0, step_ms: float = 2.5,
                      gated: bool = True) -> float:
    """Score a received signal against a reference, the way a verifier would.

    Two things a real verifier does that a naive BER does not:

    ALIGNMENT. Framing is anchored to RTP timestamps in deployment, so both ends
    frame identically and no search is needed. When the offset is unknown, a
    sub-frame search is required, because a 5 ms offset against a 20 ms hop is a
    quarter-frame misalignment and reads as near-chance. The search here runs in
    the sample domain so it can resolve below one frame.

    GATING. See the note above.
    """
    max_shift = int(round(max_shift_ms * p.fs / 1000.0))
    step = max(1, int(round(step_ms * p.fs / 1000.0)))

    ref_bits = digest_bits(ref_x, p)
    mask = activity_mask(ref_x, p) if gated else None
    if len(ref_bits) == 0:
        return 0.5

    best = float("nan")
    for s in range(-max_shift, max_shift + 1, step):
        if s >= 0:
            cand = recv_x[s:]
        else:
            cand = np.concatenate([np.zeros(-s), recv_x])
        if len(cand) < p.frame_samples * 2:
            continue
        b = digest_bits(cand, p)
        score = ber_gated(ref_bits, b, mask) if gated else ber(ref_bits, b)
        if np.isnan(score):
            continue
        best = score if np.isnan(best) else min(best, score)

    return best


# ---------------------------------------------------------------------------
# Merkle commitment - the bytes32 that reaches the chain
# ---------------------------------------------------------------------------

def _keccak_like(data: bytes) -> bytes:
    """SHA3-256. Stands in for keccak256 here; the contract uses keccak256.

    The distinction does not affect any measurement in this file, which is
    about digest robustness, not about the hash. The production client must use
    keccak256 to match the contract.
    """
    import hashlib
    return hashlib.sha3_256(data).digest()


def pack_frames(bits: np.ndarray) -> list:
    """One bytes object per frame, for use as Merkle leaves."""
    return [np.packbits(row).tobytes() for row in bits]


def merkle_root(leaves: list) -> bytes:
    """Binary Merkle root, odd nodes duplicated. Matches the JS implementation
    in test/claims.test.js so the two agree on the value committed."""
    if not leaves:
        return b"\x00" * 32
    level = [_keccak_like(l) for l in leaves]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(_keccak_like(a + b))
        level = nxt
    return level[0]


def digest_root(x: np.ndarray, p: DigestParams) -> bytes:
    """The 32 bytes that go on chain, regardless of how long the call was.

    This is the mechanism behind the constant-cost claim: the argument to
    anchorSession is this value, and its size does not depend on len(x).
    """
    return merkle_root(pack_frames(digest_bits(x, p)))
