#!/usr/bin/env python3
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from digest import DigestParams, digest_bits, ber, activity_mask, ber_gated, align_and_compare
import channel as ch
import sidechannel as sc
import speech

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results")

def run_t4(params):
    channels = sc.default_channels()
    print("=" * 70)
    print("T4 - DIGEST BIT RATE vs SIDE CHANNEL CAPACITY")
    print("=" * 70)
    print(f"Parameters: {params.label()}")
    print(f"Bit rate:   {params.bit_rate:.0f} bps ({params.bytes_per_second:.0f} B/s)\n")
    print(f"{'Channel':<46} {'Capacity':>10} {'Fits?':>8}")
    print("-" * 70)
    for c in channels:
        fits = params.bit_rate * 1.25 <= c.capacity_bps
        print(f"{c.name:<46} {c.capacity_bps:>8.0f}   {'YES' if fits else 'no':>5}")
    print()

def build_conditions(fs, rng):
    benign = [
        ("G.711 mu-law",        lambda x, o: ch.mulaw_encode_decode(ch.bandlimit(x, fs))),
        ("transcode chain x2",  lambda x, o: ch.transcode_chain(x, fs, rng)),
        ("noise 20 dB SNR",     lambda x, o: ch.bandlimit(ch.add_noise(x, 20, rng), fs)),
        ("noise 15 dB SNR",     lambda x, o: ch.bandlimit(ch.add_noise(x, 15, rng), fs)),
        ("packet loss 3%",      lambda x, o: ch.packet_loss(ch.bandlimit(x, fs), fs, 0.03, rng)),
    ]
    adversarial = [
        ("A4 full substitution", lambda x, o: ch.mulaw_encode_decode(ch.bandlimit(ch.substitute_full(x, o), fs))),
        ("A4 splice 50%",        lambda x, o: ch.mulaw_encode_decode(ch.bandlimit(ch.substitute_splice(x, o, 0.50, rng, fs), fs))),
        ("A4 splice 25%",        lambda x, o: ch.mulaw_encode_decode(ch.bandlimit(ch.substitute_splice(x, o, 0.25, rng, fs), fs))),
        ("A4 splice 10%",        lambda x, o: ch.mulaw_encode_decode(ch.bandlimit(ch.substitute_splice(x, o, 0.10, rng, fs), fs))),
        ("A4 splice 5%",         lambda x, o: ch.mulaw_encode_decode(ch.bandlimit(ch.substitute_splice(x, o, 0.05, rng, fs), fs))),
        ("replay offset 1.0 s",  lambda x, o: ch.mulaw_encode_decode(ch.bandlimit(ch.replay_offset(x, fs, 1.0), fs))),
        ("time reversed",        lambda x, o: ch.mulaw_encode_decode(ch.bandlimit(ch.time_reverse(x), fs))),
    ]
    return benign, adversarial

def run_e2(params, corpus, fs, seed=7):
    rng = np.random.default_rng(seed)
    benign_conds, adv_conds = build_conditions(fs, rng)
    n = len(corpus)
    per_cond = {}
    for i, (name, x) in enumerate(corpus):
        ref_bits = digest_bits(x, params)
        if len(ref_bits) < 20:
            continue
        mask = activity_mask(x, params)
        j = (i + 1) % n
        impostor = corpus[j][1]
        for label, fn in benign_conds:
            y = fn(x, impostor)
            score = align_and_compare(x, y, params, gated=True)
            per_cond.setdefault(("benign", label), []).append(score)
        for label, fn in adv_conds:
            y = fn(x, impostor)
            b = digest_bits(y, params)
            score = ch.windowed_gated_max_ber(ref_bits, b, mask)
            per_cond.setdefault(("adversarial", label), []).append(score)
    return per_cond

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=None)
    ap.add_argument("--speakers", type=int, default=10)
    ap.add_argument("--utterances", type=int, default=3)
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--bands", type=int, default=17)
    ap.add_argument("--hop-ms", type=float, default=20.0)
    args = ap.parse_args()

    fs = 8000
    os.makedirs(RESULTS, exist_ok=True)
    params = DigestParams(fs=fs, n_bands=args.bands, hop_ms=args.hop_ms)

    run_t4(params)

    if args.corpus:
        corpus = speech.load_corpus(args.corpus, fs=fs)
        synthetic = False
    else:
        print("!! " + speech.IS_SYNTHETIC_WARNING + "\n")
        corpus = speech.synth_corpus(args.speakers, args.utterances, args.duration, fs)
        synthetic = True

    print("=" * 70)
    print("E2 - DIGEST SEPARABILITY (Table 2)")
    print("=" * 70)
    print(f"Corpus: {'SYNTHETIC' if synthetic else args.corpus} ({len(corpus)} utterances)")
    print(f"Params: {params.label()}\n")

    per_cond = run_e2(params, corpus, fs)

    print(f"{'Kind':<13} {'Condition':<26} {'N':>4} {'Mean BER':>9} {'Max BER':>9}")
    print("-" * 70)
    rows = []
    for (kind, label), scores in sorted(per_cond.items()):
        arr = np.array([s for s in scores if not np.isnan(s)], float)
        if len(arr) == 0:
            continue
        print(f"{kind:<13} {label:<26} {len(arr):>4} {arr.mean():>9.4f} {arr.max():>9.4f}")
        rows.append({"kind": kind, "condition": label, "n": len(arr),
                     "mean": float(arr.mean()), "max": float(arr.max()),
                     "p95": float(np.percentile(arr, 95))})

    genuine = np.array([s for (k,_),v in per_cond.items() if k=="benign"
                        for s in v if not np.isnan(s)])
    impostor = np.array([s for (k,_),v in per_cond.items() if k=="adversarial"
                         for s in v if not np.isnan(s)])

    thr = float(np.percentile(genuine, 99)) if len(genuine) else 0.5
    detection = float(np.mean(impostor > thr)) if len(impostor) else 0.0

    print("-" * 70)
    print(f"Benign mean BER:     {genuine.mean():.4f}  max: {genuine.max():.4f}")
    print(f"Adversarial mean:    {impostor.mean():.4f}  min: {impostor.min():.4f}")
    print(f"Threshold (thr*):    {thr:.4f}  (99th pct of benign)")
    print(f"Detection at thr*:   {detection*100:.1f}%")

    out = {"synthetic": synthetic, "params": params.to_dict(),
           "conditions": rows,
           "aggregate": {"benign_mean": float(genuine.mean()),
                         "adversarial_mean": float(impostor.mean()),
                         "threshold": thr, "detection_rate": detection}}

    with open(os.path.join(RESULTS, "table2_separability.json"), "w") as f:
        json.dump(out, f, indent=2)

    tex_rows = "\n".join(
        f"\\quad {r['condition']} & {r['mean']:.4f} & {r['p95']:.4f} & {r['max']:.4f} \\\\"
        for r in rows
    )
    tex = f"""\\begin{{table}}[t]
\\centering
\\caption{{Robust digest separability. {'SYNTHETIC SIGNALS — re-run on real speech.' if synthetic else ''}}}
\\label{{tab:digest}}
\\begin{{tabular}}{{lrrr}}
\\toprule
Condition & Mean BER & p95 & Max \\\\
\\midrule
{tex_rows}
\\bottomrule
\\end{{tabular}}
\\end{{table}}"""
    with open(os.path.join(RESULTS, "table2_separability.tex"), "w") as f:
        f.write(tex)

    print(f"\nWritten to {RESULTS}/table2_separability.{{json,tex}}")

if __name__ == "__main__":
    main()
