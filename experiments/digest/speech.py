import numpy as np

IS_SYNTHETIC_WARNING = (
    "Signals are SYNTHETIC, not recorded speech. "
    "Numbers below validate the pipeline only. "
    "Re-run with real speech before reporting Table 2."
)

def synth_utterance(duration_s=3.0, fs=8000, f0=120.0, seed=0):
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    t = np.linspace(0, duration_s, n)
    harmonics = sum(
        (1.0 / k) * np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 2 * np.pi))
        for k in range(1, 12)
    )
    env = np.ones(n)
    fade = int(0.01 * fs)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    pauses = rng.random(n) < 0.12
    signal = harmonics * env
    signal[pauses] *= 0.02
    noise = rng.normal(0, 0.01, n)
    signal = signal + noise
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * 0.9
    return signal

def synth_corpus(n_speakers=12, utterances_per_speaker=4,
                 duration_s=3.0, fs=8000, seed=1234):
    rng = np.random.default_rng(seed)
    corpus = []
    for spk in range(n_speakers):
        f0 = float(rng.uniform(85, 210))
        for u in range(utterances_per_speaker):
            x = synth_utterance(duration_s, fs, f0=f0,
                                 seed=int(rng.integers(0, 2**31)))
            corpus.append((f"spk{spk:02d}_utt{u:02d}", x))
    return corpus

def load_corpus(directory, fs=8000, max_files=None, min_seconds=1.0):
    import glob, os
    from scipy.io import wavfile
    from scipy import signal as sps
    paths = sorted(glob.glob(os.path.join(directory, "**", "*.wav"), recursive=True))
    if max_files:
        paths = paths[:max_files]
    out = []
    for p in paths:
        sr, x = wavfile.read(p)
        x = x.astype(np.float64)
        if x.ndim > 1:
            x = x.mean(axis=1)
        if sr != fs:
            x = sps.resample(x, int(round(len(x) * fs / sr)))
        if len(x) < min_seconds * fs:
            continue
        peak = np.max(np.abs(x))
        if peak > 0:
            x = x / peak * 0.9
        out.append((os.path.basename(p), x))
    return out
