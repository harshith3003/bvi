from dataclasses import dataclass

@dataclass(frozen=True)
class SideChannel:
    name: str
    capacity_bps: float
    assumption: str
    caveat: str

def sip_info(messages_per_second=4.0, body_bytes=200):
    return SideChannel(
        name=f"SIP INFO ({messages_per_second:g} msg/s, {body_bytes} B/msg)",
        capacity_bps=messages_per_second * body_bytes * 8,
        assumption=f"{messages_per_second:g} in-dialog INFO per second, {body_bytes} raw bytes per body",
        caveat="Message rate is policy-dependent. Verify against your softswitch.",
    )

def rtp_header_extension(ptime_ms=20.0, ext_bytes=8):
    pps = 1000.0 / ptime_ms
    return SideChannel(
        name=f"RTP header ext ({ptime_ms:g} ms ptime, {ext_bytes} B/packet)",
        capacity_bps=pps * ext_bytes * 8,
        assumption=f"{pps:.0f} packets/s, {ext_bytes} bytes of RFC 8285 extension per packet",
        caveat="Extensions are stripped by middleboxes that do not understand them.",
    )

def webrtc_data_channel(effective_kbps=64.0):
    return SideChannel(
        name=f"WebRTC data channel ({effective_kbps:g} kbps budget)",
        capacity_bps=effective_kbps * 1000,
        assumption="both endpoints WebRTC",
        caveat="Does not exist on a PSTN leg.",
    )

def default_channels():
    return [
        sip_info(2.0, 200), sip_info(4.0, 400),
        rtp_header_extension(20.0, 4), rtp_header_extension(20.0, 8),
        rtp_header_extension(20.0, 16), webrtc_data_channel(64.0),
    ]

def fits(params, channel, headroom=1.25):
    return params.bit_rate * headroom <= channel.capacity_bps

def feasibility_matrix(param_list, channels=None, headroom=1.25):
    channels = channels or default_channels()
    return {
        "channels": channels,
        "rows": [{"params": p, "bit_rate": p.bit_rate,
                  "fits": [fits(p, c, headroom) for c in channels]} for p in param_list],
        "headroom": headroom,
    }
