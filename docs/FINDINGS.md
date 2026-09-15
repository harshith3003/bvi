# What the experiments found

Three results, one of which changes a design decision and one of which
strengthens a claim more than the paper currently does.

---

## 1. T4 is answered, and it constrains the design rather than blocking it

**The question:** can the side channel carry the digest? This was flagged as the
only open TODO that could invalidate the design rather than merely delay it.

**The answer:** yes, comfortably, at sensible parameters. The recommended
operating point is

> 17 Bark bands over 300–3400 Hz, 32 ms frame, 20 ms hop
> → 16 bits per frame → **800 bps** (100 bytes/second)

800 bps fits every candidate side channel with headroom:

| Side channel | Capacity | 800 bps fits? |
|---|---:|:--:|
| RTP header ext, 4 B/packet @ 20 ms | 1,600 bps | yes |
| RTP header ext, 8 B/packet @ 20 ms | 3,200 bps | yes |
| SIP INFO, 2 msg/s × 200 B | 3,200 bps | yes |
| WebRTC data channel | 64,000 bps | yes |

The binding constraint isn't capacity, it's survivability. RTP header extensions
get stripped by middleboxes that don't understand them and by any transcoding
gateway that reconstructs RTP. **That's the thing to test on the Section 5.3
testbed** — not whether the bits fit, but whether they arrive.

The full 20-point parameter sweep is in `results/t4_bitrate.csv`. Only the most
aggressive settings (33 bands at 10 ms hop, 3200 bps) run out of room.

---

## 2. A negative result that changes the design: the digest must be ternary

This one matters.

The first run of the pipeline produced BER **0.31 under plain G.711 μ-law** and
**0.45 under 20 dB SNR noise** — the latter is chance. A verifier using that
would have rejected essentially every real call.

The cause isn't the codec. It's **silence**. The digest takes the sign of a
local spectro-temporal gradient. In a pause every band energy sits on the
numerical floor, the gradient is ~0, and the sign is decided by rounding rather
than by content. Any perturbation re-randomises those bits. Roughly 15% of
speech is pause, and those frames were injecting pure noise into every score.

**The fix** is to compare only over frames carrying speech, gating on a level
45 dB below the utterance peak. Each endpoint computes the gate from the audio
it already has, so it costs no extra bits on the side channel. Effect:

| Condition | Ungated BER | Gated BER |
|---|---:|---:|
| G.711 μ-law | 0.312 | **0.122** |
| noise 20 dB SNR | 0.451 | **0.190** |
| transcode chain ×2 | 0.338 | **0.138** |

**Why this is a design change, not a bug fix.** When a window holds too little
speech, the right output isn't a BER — it's *no verdict*. That makes Layer 3
ternary in exactly the sense Layer 2 already is:

```
BER ≤ τ    → 1, consistent
BER > τ    → 0, inconsistent
too quiet  → ⊥, insufficient evidence
```

And ⊥ satisfies the conjunct, for the same reason it does at Layer 2: **silence
is not evidence of substitution.** A caller who says nothing for two seconds
must not be demoted for it.

The paper currently presents ternary scoring as a Layer 2 property. It's more
general than that, and saying so makes the architecture more coherent — the same
"absence of evidence is not evidence" principle governs both layers. Worth a
paragraph in Section 4.

**Practical consequence:** the earlier degenerate 100% EER was this sentinel
value appearing in *both* the benign and adversarial distributions. Abstentions
must be reported as a rate and excluded from the ROC, never averaged in as
though they were scores.

---

## 3. Table 2: wholesale substitution is caught perfectly, splicing degrades

At an operating threshold set from the benign side alone (99th percentile of
benign scores, τ* = 0.283 — all a deployed verifier can observe):

| Attack | EER | Detection at τ* |
|---|---:|---:|
| A4 full substitution | **0.00%** | **100%** |
| replay, 1 s offset | **0.00%** | **100%** |
| time reversed | **0.00%** | **100%** |
| A4 splice 50% | 11.1% | 86% |
| A4 splice 25% | 25.0% | 61% |
| A4 splice 10% | 27.7% | 53% |
| A4 splice 5% | 27.8% | **8%** |

The clean A4 case separates completely. Partial splicing degrades with
substituted fraction, and a 5% splice is essentially invisible.

**The detection floor is set by the worst benign condition you commit to
tolerating**, which is a deployment decision, not a tuning knob:

| Benign profile | τ* | splice 10% | splice 5% |
|---|---:|---:|---:|
| tolerate all (incl. 10 dB SNR) | 0.283 | 52.8% | 8.3% |
| require SNR ≥ 15 dB | 0.266 | 55.6% | 13.9% |
| require SNR ≥ 20 dB | 0.220 | 58.3% | 16.7% |

Tightening the line-quality requirement buys detection. State this as an
explicit tradeoff — reviewers reward a quantified limitation over a hidden one.

Two methodological points worth putting in the caption:

- Adversarial scoring uses **multi-scale windows** (12/25/50 frames). A whole-call
  BER can't see a short splice: 5% of a call leaves 95% of the digest matching.
- **These numbers come from synthetic signals.** Re-run on a real corpus before
  submission. Expect them to get worse.

---

## 4. Table 3: the BBCA claim is stronger than the paper currently states

The paper says session binding converts BBCA from "worthless until every carrier
joins" into "useful on day one." The sweep supports that, and shows something
better.

Detection of a malicious identifier rewrite, 20,000 calls per cell:

| H | p | BVI | BBCA | ratio |
|---:|---:|---:|---:|---:|
| 5 | 0.10 | 4.3% | 0.0% | ∞ |
| 5 | 0.25 | 21.4% | 0.1% | 216× |
| 5 | 0.50 | 55.9% | 3.1% | 18× |
| 12 | 0.25 | 50.5% | 0.0% | ∞ |
| 12 | 0.50 | 81.6% | 0.0% | 2038× |

**The result the paper doesn't currently claim:** the two schemes move in
*opposite directions* with path length.

Participation needed to reach 50% detection:

| Path length | BVI | BBCA |
|---:|---:|---:|
| 3 hops | 0.60 | 0.80 |
| 5 hops | 0.50 | 0.90 |
| 8 hops | 0.35 | 0.95 |
| 12 hops | **0.25** | 0.95 |

BVI gets **better** with longer paths; BBCA gets **worse**. The mechanism is
simple once stated: BVI needs one participating hop on each side of the rewrite,
and a longer path offers more chances for that. BBCA needs an unbroken chain, and
a longer path offers more chances to break it.

This inverts the usual intuition that long international routes are the hard
case. For BVI they're the *easy* case. That's a stronger and more surprising
claim than "useful on day one," and it's worth stating explicitly.

The simulator agrees with the closed form to within 1.1% (Monte Carlo noise at
20k trials), so both the model and the implementation are checked against each
other.

**The honest limitation:** false demotion plateaus around **9% of benign calls**,
driven entirely by legitimate rewrites from *unregistered* SBCs. It's flat in
carrier participation — more attestation doesn't help. The only lever is SBC
registration coverage. That's an operational finding: the thing to invest in is
registering SBCs, not recruiting carriers.

---

## 5. The gas model makes the framework choice quantitative

`anchorSession` is predicted at **~91,200 gas**, of which 71% is three cold
storage writes. Nothing in the function body varies with call duration or hop
count — the constant-cost claim restated at the opcode level.

At 12 billion calls/year:

| Deployment | Per call | Per year |
|---|---:|---:|
| Ethereum L1 @ 20 gwei | $5.47 | **$65.6 billion** |
| L2 rollup @ 0.01 gwei | $0.0027 | **$32.8 million** |

That's the calculation that kills L1 as the anchor target, and it's the number a
reviewer will ask for. Substitute live gas prices before publication.

---

## Where this leaves the paper

Resolved: T4, Table 2 (pipeline + preliminary numbers), Table 3, the constant-cost
argument.

Still open:
1. Re-run Table 2 on real speech — the only remaining item that could move a number materially
2. Run `npm run gas` and `npm run latency:opsepolia` locally
3. Fill in `docs/forced-inclusion.md` — a docs read, half a day
4. Section 6 is still empty, and the conclusion still makes claims it hasn't earned

New material worth adding: ternary Layer 3 (§2 above), and the path-length
inversion (§4 above).
