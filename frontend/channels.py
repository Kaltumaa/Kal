"""SMS and WhatsApp as the farmer sees them: channel logos, a status strip and a phone-screen preview of the thread.

Everything is drawn inline (SVG + CSS), no image files. When a farm has no messages yet, a clearly labelled sample
conversation shows what the farmer would receive.
"""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

WA_GREEN, WA_DARK, WA_BUBBLE, WA_BG = "#25D366", "#075E54", "#DCF8C6", "#ECE5DD"
SMS_BLUE = "#0B84FF"

# Channel marks, drawn for this app (simple shapes, not the companies' artwork).
WHATSAPP_LOGO = (
    '<svg width="{s}" height="{s}" viewBox="0 0 48 48" role="img" aria-label="WhatsApp">'
    f'<path d="M24 4C13 4 4 12.6 4 23.3c0 3.8 1.1 7.3 3.1 10.3L5 44l10.8-2.9c2.5 1.2 5.3 1.8 8.2 1.8 11 0 20-8.6 '
    f'20-19.3S35 4 24 4z" fill="{WA_GREEN}"/>'
    '<path d="M17.5 14.5c.6 0 1 .1 1.3.8l1.9 4.4c.2.5.1 1-.2 1.4l-1.4 1.7c1.4 2.7 3.6 4.9 6.3 6.3l1.7-1.4c.4-.3.9-.4 '
    '1.4-.2l4.4 1.9c.6.3.8.7.8 1.3 0 2.5-2.3 4.3-4.8 3.9-7.1-1.1-12.7-6.7-13.8-13.8-.4-2.5 1.4-4.8 3.9-4.8z" '
    'fill="#fff"/></svg>')
SMS_LOGO = (
    '<svg width="{s}" height="{s}" viewBox="0 0 48 48" role="img" aria-label="SMS">'
    f'<rect x="2" y="2" width="44" height="44" rx="12" fill="{SMS_BLUE}"/>'
    '<path d="M24 11c-8.8 0-16 5.7-16 12.7 0 4 2.3 7.5 5.9 9.8L12.5 39l6.6-3.4c1.5.4 3.2.6 4.9.6 8.8 0 16-5.7 '
    '16-12.7S32.8 11 24 11z" fill="#fff"/>'
    f'<circle cx="17" cy="23.7" r="2.2" fill="{SMS_BLUE}"/><circle cx="24" cy="23.7" r="2.2" fill="{SMS_BLUE}"/>'
    f'<circle cx="31" cy="23.7" r="2.2" fill="{SMS_BLUE}"/></svg>')
TALO_AVATAR = ('<svg width="34" height="34" viewBox="0 0 34 34"><circle cx="17" cy="17" r="17" fill="#2F6417"/>'
               '<path d="M17 25V14m0 3c-3.5 0-5.5-2.2-5.5-5.2 3.5 0 5.5 2.2 5.5 5.2zm0-1c0-3.3 2-5.6 5.6-5.6 0 '
               '3.3-2 5.6-5.6 5.6z" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round"/></svg>')

CSS = """<style>
.ch-head{display:flex;align-items:center;gap:14px;margin:4px 0 10px}
.ch-head h4{margin:0;font-size:1.15rem}
.ch-chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.75rem;font-weight:600}
.ch-live{background:#E6F7EC;color:#137333}.ch-sim{background:#FFF4E0;color:#8A5300}
.ch-stats{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 4px}
.ch-stat{border:1px solid #E7E7E2;border-radius:10px;padding:8px 14px;min-width:92px;background:#fff}
.ch-stat b{display:block;font-size:1.25rem}.ch-stat span{font-size:.72rem;color:#71717A;text-transform:uppercase}
.ph{width:300px;max-width:100%;margin:6px auto;border:10px solid #18181B;border-radius:34px;overflow:hidden;
 box-shadow:0 18px 40px rgba(0,0,0,.18);background:#fff;font-family:-apple-system,Segoe UI,Roboto,sans-serif}
.ph-notch{height:18px;background:#18181B;display:flex;justify-content:center}
.ph-notch i{width:90px;height:12px;background:#000;border-radius:0 0 10px 10px}
.ph-bar{display:flex;align-items:center;gap:9px;padding:9px 12px}
.ph-bar .nm{font-weight:600;font-size:.86rem;line-height:1.1}.ph-bar .sb{font-size:.68rem;opacity:.8}
.ph-body{height:390px;overflow-y:auto;padding:10px 9px;display:flex;flex-direction:column;gap:6px}
.bb{max-width:82%;padding:6px 9px 4px;border-radius:10px;font-size:.8rem;line-height:1.35;word-wrap:break-word;
 box-shadow:0 1px 0 rgba(0,0,0,.08);white-space:pre-wrap}
.bb .mt{display:block;text-align:right;font-size:.62rem;opacity:.65;margin-top:2px}
.bb.in{align-self:flex-start}.bb.out{align-self:flex-end}
.wa .ph-bar{background:#075E54;color:#fff}.wa .ph-body{background:#ECE5DD}
.wa .bb.in{background:#fff;border-top-left-radius:2px}.wa .bb.out{background:#DCF8C6;border-top-right-radius:2px}
.sms .ph-bar{background:#F4F4F5;color:#18181B;border-bottom:1px solid #E4E4E7;flex-direction:column;gap:3px}
.sms .ph-body{background:#fff}.sms .bb{border-radius:16px}
.sms .bb.in{background:#E9E9EB;color:#111}.sms .bb.out{background:#0B84FF;color:#fff}
.ph-day{align-self:center;font-size:.64rem;background:rgba(255,255,255,.85);color:#555;padding:2px 8px;
 border-radius:6px;margin:4px 0}
.sms .ph-day{background:none;color:#8E8E93}
.ph-sample{align-self:center;font-size:.66rem;background:#FFF4E0;color:#8A5300;padding:3px 9px;border-radius:999px}
.ph-input{display:flex;gap:6px;align-items:center;padding:7px 9px;border-top:1px solid #E4E4E7;font-size:.75rem;
 color:#A1A1AA}.ph-input div{flex:1;border:1px solid #E4E4E7;border-radius:999px;padding:5px 10px}
.wa .ph-input{background:#F0F0F0}
</style>"""

SAMPLE = {
    "whatsapp": [
        ("in", "2026-10-15T07:02", "TALO: Hold field work on your maize today. Heavy rain is coming (34 mm in 24 "
                                   "hours). Do not spray or apply fertiliser until it passes. - Wanjiru Kamau, "
                                   "Dagoretti South Extension", "SENT"),
        ("out", "2026-10-15T07:15", "LOG WEEDING top field", "RECEIVED"),
        ("in", "2026-10-15T07:15", "Saved to your plot history: weeding today.", "SENT"),
        ("out", "2026-10-15T09:40", "PROBLEM holes in maize leaves, sawdust in the funnel", "RECEIVED"),
        ("in", "2026-10-15T09:40", "Received. Your extension officer will check it and reply.", "SENT"),
    ],
    "sms": [
        ("in", "2026-10-15T07:02", "TALO: Subiri kupanda. Mvua kubwa inakuja (mm 34 kwa saa 24). Usinyunyize dawa "
                                   "wala mbolea hadi ipite. - Wanjiru Kamau", "SIMULATED"),
        ("out", "2026-10-15T08:10", "KUMBUSHA kesho NYUNYIZA", "RECEIVED"),
        ("in", "2026-10-15T08:10", "Kikumbusho kimewekwa 2026-10-16: spraying.", "SIMULATED"),
    ],
}


NAIROBI = ZoneInfo("Africa/Nairobi")


def _local(ts: str | None) -> datetime | None:
    """Stored times are UTC (with an offset); show them as the farmer's clock, Nairobi time."""
    try:
        t = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return t.astimezone(NAIROBI) if t.tzinfo else t


def _time(ts: str | None) -> str:
    t = _local(ts)
    return t.strftime("%H:%M") if t else ""


def _day(ts: str | None) -> str:
    t = _local(ts)
    return t.strftime("%a %d %b") if t else ""


def _ticks(status: str, channel: str) -> str:
    if channel == "whatsapp":
        return {"SENT": ' <span style="color:#34B7F1">✓✓</span>', "SIMULATED": ' <span style="color:#999">✓✓</span>',
                "FAILED": ' <span style="color:#D93025">!</span>'}.get(status, "")
    return {"FAILED": " · Not delivered"}.get(status, "")


def header(channel: str, title: str, live: bool, detail: str, stats: list[tuple[str, int | str]]) -> None:
    logo = (WHATSAPP_LOGO if channel == "whatsapp" else SMS_LOGO).format(s=44)
    chip = '<span class="ch-chip ch-live">● Live</span>' if live else '<span class="ch-chip ch-sim">● Simulated</span>'
    boxes = "".join(f'<div class="ch-stat"><b>{html.escape(str(v))}</b><span>{html.escape(k)}</span></div>'
                    for k, v in stats)
    st.markdown(CSS + f'<div class="ch-head">{logo}<div><h4>{html.escape(title)} {chip}</h4>'
                f'<div style="font-size:.8rem;color:#71717A">{html.escape(detail)}</div></div></div>'
                f'<div class="ch-stats">{boxes}</div>', unsafe_allow_html=True)


def phone(channel: str, contact: str, subtitle: str, messages: list[tuple[str, str, str, str]]) -> None:
    """messages: (direction 'in'|'out' from the FARMER's phone, iso time, text, status). Empty = sample thread."""
    sample = not messages
    rows = SAMPLE[channel] if sample else messages
    parts, last_day = [], None
    if sample:
        parts.append('<div class="ph-sample">Sample conversation: no messages for this farm yet</div>')
    for direction, ts, text, status in rows:
        day = _day(ts)
        if day and day != last_day:
            parts.append(f'<div class="ph-day">{day}</div>')
            last_day = day
        tick = _ticks(status, channel) if direction == "in" else ""
        parts.append(f'<div class="bb {direction}">{html.escape(text)}'
                     f'<span class="mt">{_time(ts)}{tick}</span></div>')
    if channel == "whatsapp":
        bar = (f'<div class="ph-bar">{TALO_AVATAR}<div><div class="nm">TALO Extension</div>'
               f'<div class="sb">{html.escape(subtitle)}</div></div></div>')
        inp = '<div class="ph-input"><div>Message</div>' + WHATSAPP_LOGO.format(s=22) + '</div>'
    else:
        bar = (f'<div class="ph-bar">{TALO_AVATAR}<div class="nm">TALO</div>'
               f'<div class="sb">{html.escape(subtitle)}</div></div>')
        inp = '<div class="ph-input"><div>Text Message</div>' + SMS_LOGO.format(s=22) + '</div>'
    st.markdown(f'<div class="ph {"wa" if channel == "whatsapp" else "sms"}"><div class="ph-notch"><i></i></div>'
                f'{bar}<div class="ph-body">{"".join(parts)}</div>{inp}</div>'
                f'<div style="text-align:center;font-size:.72rem;color:#71717A;margin-top:4px">'
                f'{html.escape(contact)}\'s phone</div>', unsafe_allow_html=True)
