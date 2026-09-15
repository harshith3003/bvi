# Forced inclusion delay — the last piece of the §4.2 argument

**Status: NOT DONE. Half a day of docs reading. Blocks a claim in Section 4.2.**

## Why this matters

`test/revocation.test.js` proves four of the five properties in the sentence
"immediately visible to every verifier and suppressible by none":

- two independent principals can revoke, so compromising one doesn't block it
- revocation is terminal and can't be undone
- the effect is immediate, with no settlement window
- it's observable via an indexed event, without polling

The fifth — **inclusion** — is not a contract property and no Solidity test can
establish it. A rollup sequencer can't forge state, because batch data goes to
L1 and anyone can reconstruct the L2 independently. But it *can* decline to
include a transaction it's been handed, because it controls ordering.

That is exactly the single operator §4.2 excludes.

## What to find out

Fill this in from the rollup's own documentation, not from a blog post:

| Question | Answer | Source |
|---|---|---|
| What is the forced-inclusion mechanism called? | | |
| How does a user submit through it? | | |
| What is the **worst-case** delay before inclusion is guaranteed? | | |
| Is that delay a protocol constant or an operator parameter? | | |
| Can the sequencer censor the forced-inclusion path itself? | | |
| Is there a delay before the escape hatch becomes usable? | | |

Also verify, since it bears on R2:

| Question | Answer | Source |
|---|---|---|
| Can a client subscribe to `StatusChanged` via a public RPC, no own node? | | |
| Are indexed event filters supported on public endpoints? | | |
| Rate limits that would matter for a handset client? | | |

## How the answer decides the design

**If the worst-case delay is bounded and short** (minutes): the L1/L2 split is
tidy rather than necessary. Say so explicitly, cite the number, and note that
revocation on L1 is a defence-in-depth choice.

**If it's hours, or an operator parameter**: the split is *required*, and that's
a stronger result. Revocation goes to L1; only anchors go to the L2. State it as
a design decision with the delay figure as justification.

Either way this becomes one sentence with a citation. What must not happen is a
reviewer discovering the question before you've answered it.

## Write-up target

Section 4.2, one paragraph. Something like: "Revocation is submitted to the L1
instance. On a rollup, the sequencer controls transaction ordering and can delay
inclusion by up to [N]; the forced-inclusion path guarantees eventual inclusion
within [M] but not promptness. Since §4.2 requires the effect be suppressible by
none, revocation bypasses the sequencer entirely."
