import numpy as np
from scipy import signal as sps

def mulaw_encode_decode(x, mu=255):
    x = np.clip(x, -1.0, 1.0)
    y = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    q = np.round((y + 1.0) * 127.5)
    y_hat = q / 127.5 - 1.0
    return np.sign(y_hat) * (1.0 / mu) * ((1.0 + mu) ** np.abs(y_hat) - 1.0)

def bandlimit(x, fs, lo=300.0, hi=3400.0):
    nyq = fs / 2.0
    hi = min(hi, nyq * 0.99)
    sos = sps.butter(6, [lo / nyq, hi / nyq], btype="band", output="sos")
    return sps.sosfiltfilt(sos, x)

def add_noise(x, snr_db, rng):
    p_sig = np.mean(x ** 2)
    if p_sig <= 0:
        return x
    p_noise = p_sig / (10.0 ** (snr_db / 10.0))
    return x + rng.normal(0, np.sqrt(p_noise), size=x.shape)

def packet_loss(x, fs, loss_rate, rng, ptime_ms=20.0):
    n = int(round(ptime_ms * fs / 1000.0))
    if n <= 0 or loss_rate <= 0:
        return x.copy()
    y = x.copy()
    n_pkts = len(x) // n
    for i in range(n_pkts):
        if rng.random() < loss_rate:
            s, e = i * n, (i + 1) * n
            y[s:e] = y[(i-1)*n:i*n] * 0.5 if i > 0 else 0.0
    return y

def transcode_chain(x, fs, rng):
    y = bandlimit(x, fs)
    y = mulaw_encode_decode(y)
    return bandlimit(y, fs)

def substitute_full(x, other):
    n = len(x)
    if len(other) >= n:
        return other[:n].copy()
    return np.tile(other, int(np.ceil(n / len(other))))[:n]

def substitute_splice(x, other, frac, rng, fs=8000):
    n = len(x)
    seg = int(round(frac * n))
    if seg <= 0:
        return x.copy()
    start = int(rng.integers(0, max(1, n - seg)))
    src = other if len(other) >= seg else np.tile(other, int(np.ceil(seg / len(other))))
    y = x.copy()
    y[start:start + seg] = src[:seg]
    return y

def replay_offset(x, fs, offset_s):
    n = int(round(offset_s * fs))
    if n <= 0 or n >= len(x):
        return x.copy()
    return np.concatenate([x[n:], x[:n]])

def time_reverse(x):
    return x[::-1].copy()

def windowed_gated_max_ber(ref_bits, recv_bits, mask=None,
                            window_scales=(12, 25, 50), hop_frac=0.5,
                            min_active=8):
    from digest import ber_gated
    n = min(len(ref_bits), len(recv_bits))
    if n == 0:
        return float("nan")
    if mask is None:
        mask = np.ones(n, dtype=bool)
    mask = mask[:n]
    worst = float("nan")
    for w in window_scales:
        if w > n:
            continue
        hop = max(1, int(w * hop_frac))
        for s in range(0, n - w + 1, hop):
            e = s + w
            seg = mask[s:e]
            if seg.sum() < min_active:
                continue
            score = ber_gated(ref_bits[s:e], recv_bits[s:e], seg, min_active)
            if np.isnan(score):
                continue
            worst = score if np.isnan(worst) else max(worst, score)
    if np.isnan(worst):
        worst = ber_gated(ref_bits[:n], recv_bits[:n], mask, min_active)
    return worst
