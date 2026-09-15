# The verifier's decision procedure

Reference for the client implementation. Every step is a `view` call, so the
recipient needs no account and pays nothing.

```
INPUT: presented identifier, session assertion, nonce
       sid = H(nonce || chid)

LAYER 1 — identity                                    [BLOCKING, call setup]
  rec = resolve(did)                                  L1 instance
  if rec.status != Active                        -> REJECT
  if !isAuthorisedChannel(did, H(identifier))    -> REJECT
  if !verify(assertion, rec.pubKeyHash, rec.keyEpoch) -> REJECT
  score_1 = 1

LAYER 2 — path                                        [non-blocking]
  atts = getAttestations(sid)                         L2 instance
  if any participating hop contradicts           -> score_2 = 0
  elif |atts| >= k and all consistent            -> score_2 = 1
  else                                           -> score_2 = ⊥

LAYER 3 — content                                     [continuous, during call]
  compare received digest against locally computed, gated to active frames,
  over multi-scale windows
  if max windowed BER > τ                        -> score_3 = 0
  elif enough active frames                      -> score_3 = 1
  else                                           -> score_3 = ⊥

CONJUNCT
  ⊥ SATISFIES. Only an explicit 0 fails.
  verified = (score_1 == 1) and (score_2 != 0) and (score_3 != 0)

LAYER 4 — liveness                                    [may only demote]
  if verified and detector fires above threshold -> DEMOTE, never PROMOTE

TEARDOWN                                              [off critical path]
  anchorSession(sid, merkleRoot(digests), H(transcript))   L2 instance
```

## Why ⊥ satisfies

The same principle at both layers: **absence of evidence is not evidence of
absence.**

At Layer 2, a path no carrier attested isn't suspicious — it's unobserved. Treating
it as failure is precisely BBCA's problem, and it's what makes BBCA useless below
full participation.

At Layer 3, a caller who is silent for two seconds produces no content to
authenticate. Demoting for that would fail on every natural pause.

## Which instance to read

| Call | Instance | Why |
|---|---|---|
| `resolve` | **L1** | status must reflect revocation without sequencer delay |
| `isAuthorisedChannel` | **L1** | same record |
| `getAttestations` | L2 | per-session, written cheaply |
| `getAnchor` | L2 | per-session |
| `anchorSession` | L2 | the recurring write |
| `setStatus` | **L1** | inclusion must not be gateable — §4.2 |

## Latency budget (R9)

Only Layer 1 blocks call setup. That's two reads:
`resolve` + `isAuthorisedChannel`. `scripts/measure-latency.js` times exactly
that pair as a composite, since it's the quantity R9 constrains. Report p95 and
p99, not the mean — the tail is what breaks a budget.
