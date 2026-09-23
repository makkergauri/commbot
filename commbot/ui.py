"""
Everything that decides how the control room looks.

The brief was a room you'd want to stand in: dark, calm, with the numbers
that matter glowing and everything else out of the way. Colour carries
meaning here, never decoration. Red means extreme, amber means serious, and
the pulsing dots on the map are alerts that are live this minute.

No JavaScript and no build step. Every chart, the map and the animations are
SVG or CSS, so the page still works on a weak connection, which is the same
constraint the SMS side of this project lives with.
"""
from __future__ import annotations

import html

SEVERITY = {
    "Extreme": "#ff2d55",
    "Severe": "#ff7a45",
    "Moderate": "#ffc53d",
    "Minor": "#38bdf8",
    "Unknown": "#94a3b8",
}

HAZARD = {
    "FLOOD": ("Flood", "#38bdf8"),
    "HEAVY_RAIN": ("Heavy rain", "#22d3ee"),
    "THUNDERSTORM": ("Thunderstorm", "#a78bfa"),
    "CYCLONE": ("Cyclone", "#2dd4bf"),
    "EARTHQUAKE": ("Earthquake", "#fbbf24"),
    "LANDSLIDE": ("Landslide", "#f59e0b"),
    "HEATWAVE": ("Heatwave", "#fb7185"),
    "COLD_WAVE": ("Cold wave", "#60a5fa"),
    "OTHER": ("Other", "#94a3b8"),
}

NAV = [("", "Overview"), ("/alerts", "Alerts"), ("/people", "Coverage"),
       ("/activity", "Activity"), ("/about", "How it works")]

# India's boundary, simplified from DataMeet's open India composite map
# (CC-BY). 182 points is enough to be accurate at this size and small enough
# to sit in the page source.
INDIA = [
    (35.49,77.52), (35.99,79.34), (35.42,80.05), (35.48,80.41), (34.71,80.07),
    (34.45,79.51), (34.0,79.4), (33.97,78.89), (33.64,79.09), (33.38,78.94), (33.19,79.41),
    (32.68,79.55), (32.34,78.97), (32.7,78.74), (32.53,78.4), (31.99,78.78), (31.31,78.78),
    (31.45,79.1), (31.02,79.43), (30.25,81.03), (29.75,80.37), (28.82,80.08), (27.86,81.88),
    (27.72,82.71), (27.5,82.74), (27.33,83.32), (27.52,84.15), (26.76,85.21), (26.87,85.63),
    (26.57,85.85), (26.36,88.01), (27.92,88.12), (28.12,88.64), (27.86,88.89),
    (27.14,88.75), (26.81,89.13), (26.85,92.06), (27.29,92.12), (27.48,91.65),
    (27.76,91.64), (27.79,92.46), (28.15,92.68), (29.3,94.63), (29.07,95.26), (29.38,96.05),
    (28.73,96.63), (28.51,96.41), (28.61,96.71), (28.01,97.4), (27.61,96.89), (27.09,97.14),
    (27.37,96.7), (27.28,96.23), (26.62,95.15), (26.07,95.19), (25.4,94.63), (24.94,94.71),
    (23.85,94.16), (24.08,93.33), (23.13,93.39), (23.04,93.13), (22.26,93.2), (21.94,92.91),
    (22.16,92.7), (21.98,92.6), (23.72,92.28), (23.73,91.96), (22.94,91.62), (23.61,91.16),
    (24.11,91.37), (24.14,91.9), (24.42,92.16), (25.03,92.43), (25.29,89.84), (26.24,89.68),
    (26.01,89.36), (26.4,89.09), (26.26,88.67), (26.63,88.4), (26.36,88.52), (25.82,88.11),
    (25.26,89.01), (25.21,88.44), (24.67,88.01), (24.28,88.74), (23.65,88.56), (23.5,88.8),
    (23.26,88.72), (23.22,89.0), (23.01,88.84), (21.64,89.1), (21.68,88.72), (22.08,88.64),
    (21.56,88.25), (22.22,88.02), (22.1,88.19), (21.7,87.8), (21.34,86.91), (20.78,86.87),
    (20.72,87.07), (19.95,86.37), (19.39,85.04), (18.31,84.13), (17.04,82.31), (16.56,82.3),
    (16.29,81.27), (15.71,80.94), (15.89,80.68), (15.67,80.26), (15.07,80.05),
    (13.28,80.35), (11.67,79.76), (10.31,79.88), (10.26,79.29), (9.49,78.9), (9.28,79.19),
    (9.02,78.27), (8.37,78.07), (8.07,77.55), (8.9,76.55), (11.12,75.87), (12.0,75.2),
    (14.24,74.52), (16.05,73.46), (18.69,72.86), (19.02,73.07), (19.19,72.99),
    (18.89,72.81), (19.52,72.89), (19.83,72.66), (20.76,72.93), (21.3,72.6), (21.68,72.93),
    (21.66,72.54), (21.97,72.75), (21.98,72.51), (22.26,72.91), (22.31,72.33), (21.2,72.11),
    (20.69,70.82), (22.31,68.94), (22.54,70.17), (22.97,70.45), (22.84,69.2), (23.51,68.43),
    (23.88,68.81), (23.62,68.17), (23.97,68.36), (23.97,68.75), (24.31,68.81),
    (24.17,70.03), (24.4,71.12), (25.7,70.66), (25.94,70.1), (26.55,70.17), (26.74,69.51),
    (27.18,69.59), (28.01,70.37), (27.71,70.87), (27.96,71.9), (28.77,72.39), (29.03,72.95),
    (29.95,73.4), (30.2,73.97), (30.49,73.93), (31.07,74.7), (31.13,74.51), (31.89,74.61),
    (32.23,75.37), (32.49,74.68), (32.84,74.71), (33.09,73.63), (34.38,73.4), (35.12,74.13),
    (35.86,73.18), (35.85,72.57), (36.23,72.55), (36.7,73.06), (36.72,73.86), (36.92,73.67),
    (37.03,75.15), (35.49,77.52)
]

STYLE = """
:root{--bg:#05070f;--panel:rgba(255,255,255,.045);--edge:rgba(255,255,255,.09);
 --ink:#e9edf7;--dim:#8f9bb3;--cyan:#22d3ee;--violet:#a78bfa;--ok:#34d399;--bad:#ff2d55;
 --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:
  radial-gradient(1100px 620px at 12% -8%,rgba(34,211,238,.13),transparent 60%),
  radial-gradient(900px 560px at 92% 4%,rgba(167,139,250,.13),transparent 62%),var(--bg);
 color:var(--ink);font-family:"Inter",-apple-system,"Segoe UI",Roboto,system-ui,sans-serif;
 -webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.wrap{max-width:1140px;margin:0 auto;padding:0 24px}

/* nav */
.bar{display:flex;align-items:center;gap:20px;padding:18px 0;flex-wrap:wrap;
 border-bottom:1px solid var(--edge);position:sticky;top:0;z-index:20;
 background:rgba(5,7,15,.82);backdrop-filter:blur(14px)}
.logo{display:flex;align-items:center;gap:11px;font-weight:700;font-size:17px;letter-spacing:-.01em}
.logo i{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;
 background:linear-gradient(135deg,rgba(34,211,238,.25),rgba(167,139,250,.25));
 border:1px solid var(--edge)}
.nav{display:flex;gap:2px;margin-left:auto;flex-wrap:wrap}
.nav a{padding:9px 15px;border-radius:10px;font-size:14px;font-weight:600;color:var(--dim)}
.nav a:hover{color:var(--ink);background:rgba(255,255,255,.06)}
.nav a.on{color:#05070f;background:linear-gradient(135deg,var(--cyan),var(--violet))}

/* ticker */
.ticker{border-bottom:1px solid var(--edge);overflow:hidden;background:rgba(255,255,255,.02)}
.ticker .track{display:flex;gap:44px;white-space:nowrap;padding:11px 0;
 font-size:13px;color:var(--dim);animation:slide 42s linear infinite}
.ticker b{color:var(--ink);font-weight:600}
.ticker .sq{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:9px}
@keyframes slide{from{transform:translateX(0)}to{transform:translateX(-50%)}}

/* hero */
.hero{padding:62px 0 46px;display:grid;grid-template-columns:1.15fr .85fr;gap:40px;align-items:center}
.eyebrow{display:inline-flex;align-items:center;gap:9px;font-size:11.5px;font-weight:700;
 letter-spacing:.18em;text-transform:uppercase;color:var(--cyan);margin-bottom:18px}
.pulse{width:8px;height:8px;border-radius:50%;background:var(--cyan);
 box-shadow:0 0 0 0 rgba(34,211,238,.75);animation:p 2.2s infinite}
@keyframes p{70%{box-shadow:0 0 0 10px rgba(34,211,238,0)}100%{box-shadow:0 0 0 0 rgba(34,211,238,0)}}
.hero h1{font-size:clamp(34px,4.6vw,56px);line-height:1.04;letter-spacing:-.035em;margin:0 0 18px;
 font-weight:700;background:linear-gradient(120deg,#fff 20%,#9fe9f7 75%,#c4b5fd);
 -webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{margin:0;color:var(--dim);font-size:16.5px;line-height:1.65;max-width:52ch}
.readout{border:1px solid var(--edge);border-radius:20px;padding:26px;background:var(--panel)}
.readout .big{font-family:var(--mono);font-size:72px;line-height:1;letter-spacing:-.05em;
 background:linear-gradient(120deg,var(--cyan),var(--violet));-webkit-background-clip:text;
 background-clip:text;color:transparent}
.readout .cap{font-size:13px;color:var(--dim);margin-top:10px;letter-spacing:.04em}
.readout .row{display:flex;justify-content:space-between;font-size:13.5px;padding:12px 0;
 border-top:1px solid var(--edge);margin-top:16px;color:var(--dim)}
.readout .row b{color:var(--ink);font-family:var(--mono)}

/* layout bits */
main{padding:0 0 80px}
section{margin-bottom:34px}
h2{font-size:11.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--dim);
 font-weight:700;margin:0 0 16px;display:flex;align-items:center;gap:12px}
h2:after{content:"";flex:1;height:1px;background:var(--edge)}
h3{font-size:17px;margin:0 0 6px;font-weight:700;letter-spacing:-.01em}
.card{background:var(--panel);border:1px solid var(--edge);border-radius:18px}
.pad{padding:24px}
.grid{display:grid;gap:16px}
.g4{grid-template-columns:repeat(auto-fit,minmax(215px,1fr))}
.g2{grid-template-columns:1.15fr .85fr;align-items:start}
.note{font-size:13.5px;color:var(--dim);line-height:1.65;margin:0 0 18px}

/* tiles */
.tile{position:relative;overflow:hidden;padding:22px}
.tile:before{content:"";position:absolute;inset:0 0 auto 0;height:2px;opacity:.9}
.tile .ic{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;margin-bottom:16px;
 border:1px solid var(--edge)}
.tile .n{font-family:var(--mono);font-size:42px;letter-spacing:-.04em;line-height:1}
.tile .k{font-size:14.5px;font-weight:650;margin-top:10px}
.tile .s{font-size:13px;color:var(--dim);margin-top:5px;line-height:1.5}

/* alert cards */
.alert{position:relative;overflow:hidden;padding:24px;margin-bottom:16px}
.alert:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px}
.head{display:flex;align-items:center;gap:13px;flex-wrap:wrap}
.hicon{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;flex:none;
 border:1px solid var(--edge)}
.title{font-size:23px;font-weight:700;letter-spacing:-.02em}
.badge{font-size:10.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
 padding:5px 11px;border-radius:7px}
.where{font-size:17px;font-weight:600;margin-top:14px;line-height:1.45}
.meta{font-size:13px;color:var(--dim);margin-top:9px;line-height:1.6}
.flag{margin-top:14px;font-size:12.5px;color:#fbbf24;background:rgba(251,191,36,.08);
 border:1px solid rgba(251,191,36,.25);border-radius:10px;padding:10px 13px}

/* the SMS preview, drawn as a phone */
.phones{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px}
.phone{border:1px solid var(--edge);border-radius:16px;padding:14px;background:rgba(0,0,0,.28)}
.phone .top{display:flex;justify-content:space-between;font-size:10.5px;color:var(--dim);
 letter-spacing:.14em;text-transform:uppercase;font-weight:700;margin-bottom:12px}
.bubble{background:linear-gradient(135deg,rgba(34,211,238,.17),rgba(167,139,250,.17));
 border:1px solid var(--edge);border-radius:16px 16px 16px 5px;padding:13px 15px;
 font-size:14px;line-height:1.6}
.phone .len{font-family:var(--mono);font-size:11px;color:var(--dim);margin-top:10px}
.acts{display:flex;gap:11px;margin-top:20px;flex-wrap:wrap}
button{font:inherit;font-size:15px;font-weight:650;padding:14px 26px;border:0;border-radius:12px;
 cursor:pointer;transition:transform .12s ease}
button:hover{transform:translateY(-1px)}
.go{background:linear-gradient(135deg,#34d399,#10b981);color:#04231a;
 box-shadow:0 10px 26px -14px #34d399}
.no{background:transparent;color:#ff8ba3;border:1px solid rgba(255,45,85,.35)}

/* lists */
.list .item{display:flex;align-items:center;gap:15px;padding:16px 22px;border-top:1px solid var(--edge)}
.list .item:first-child{border-top:0}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
.item .nm{font-weight:650;font-size:15px}
.item .ar{color:var(--dim);font-size:13.5px;margin-top:3px;line-height:1.45}
.item .rt{margin-left:auto;text-align:right;font-size:12.5px;color:var(--dim);white-space:nowrap}
.item .rt b{display:block;color:var(--ink);font-family:var(--mono);font-size:13px}

/* chips, bars, tables */
.chips{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:16px}
.chip{font-size:13px;font-weight:600;padding:9px 16px;border-radius:11px;border:1px solid var(--edge);
 color:var(--dim);background:var(--panel)}
.chip:hover{color:var(--ink)}
.chip.on{background:linear-gradient(135deg,var(--cyan),var(--violet));color:#05070f;border-color:transparent}
.bar{margin-bottom:16px}
.bar .lbl{display:flex;justify-content:space-between;font-size:13.5px;font-weight:600;margin-bottom:8px}
.bar .lbl span:last-child{font-family:var(--mono)}
.bar .track{height:8px;border-radius:99px;background:rgba(255,255,255,.07);overflow:hidden}
.bar .fill{height:100%;border-radius:99px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);
 padding:0 0 13px;font-weight:700}
td{padding:13px 0;border-top:1px solid var(--edge);font-family:var(--mono);font-size:13px}
.pill{font-family:inherit;font-size:11.5px;font-weight:650;padding:4px 11px;border-radius:7px}
.pill.sent{background:rgba(52,211,153,.14);color:#34d399}
.pill.failed{background:rgba(255,45,85,.14);color:#ff6b8a}
.empty{color:var(--dim);font-size:14.5px;border:1px dashed var(--edge);border-radius:18px;
 padding:34px;text-align:center}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--dim);margin-top:16px}
.legend span{display:flex;align-items:center;gap:8px}
.kv{display:flex;justify-content:space-between;padding:13px 0;border-top:1px solid var(--edge);
 font-size:14px;color:var(--dim)}
.kv b{color:var(--ink);font-family:var(--mono)}
.step{display:flex;gap:20px;margin-bottom:6px}
.step .num{font-family:var(--mono);font-size:13px;color:var(--cyan);width:34px;height:34px;flex:none;
 border:1px solid var(--edge);border-radius:11px;display:grid;place-items:center;background:var(--panel)}
.step .line{width:1px;background:var(--edge);margin:6px auto 0;flex:1}
.step .col{display:flex;flex-direction:column;align-items:center;align-self:stretch}
.step .txt{padding-bottom:26px}
footer{border-top:1px solid var(--edge);padding:28px 0 56px;color:var(--dim);font-size:12.5px;
 line-height:1.7}

@media(max-width:900px){.hero{grid-template-columns:1fr;padding:38px 0 30px}
 .g2{grid-template-columns:1fr}.phones{grid-template-columns:1fr}
 .readout .big{font-size:56px}.nav{width:100%;margin-left:0}button{flex:1}}
"""

ICONS = {
    "bolt": "M13 2 4 14h6l-1 8 9-12h-6z",
    "drop": "M12 3s6 6.5 6 10a6 6 0 1 1-12 0c0-3.5 6-10 6-10z",
    "wave": "M2 15c3-3 5 3 8 0s5-3 8 0M2 9c3-3 5 3 8 0s5-3 8 0",
    "people": "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 19c0-3 3-5 6-5s6 2 6 5M14 19c0-2 1-4 3-4s5 1.5 5 4",
    "check": "M20 7 10 18l-5-5",
    "send": "M3 11 21 3l-8 18-2-7-8-3z",
    "clock": "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
    "shield": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
}


def esc(value) -> str:
    return html.escape(str(value))


def icon(name: str, colour: str = "currentColor", size: int = 18) -> str:
    path = ICONS.get(name, ICONS["bolt"])
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{colour}" stroke-width="1.9" stroke-linecap="round" '
            f'stroke-linejoin="round"><path d="{path}"/></svg>')


def hazard_name(code: str) -> str:
    return HAZARD.get(code, HAZARD["OTHER"])[0]


def hazard_colour(code: str) -> str:
    return HAZARD.get(code, HAZARD["OTHER"])[1]


def hazard_icon(code: str) -> str:
    return {"FLOOD": "wave", "HEAVY_RAIN": "drop", "THUNDERSTORM": "bolt",
            "CYCLONE": "wave", "HEATWAVE": "drop"}.get(code, "bolt")


def severity_colour(name: str) -> str:
    return SEVERITY.get(name, SEVERITY["Unknown"])


def tile(number, key, sub, colour, icon_name) -> str:
    # `key` may carry a small tag element, so it goes through as HTML.
    # Everything in it is written by me, never by a feed or a person.
    return f"""<div class="card tile" style="--c:{colour}">
      <div style="position:absolute;inset:0 0 auto 0;height:2px;background:{colour}"></div>
      <div class="ic" style="background:{colour}1f">{icon(icon_name, colour)}</div>
      <div class="n" style="color:{colour}">{number}</div>
      <div class="k">{key}</div><div class="s">{esc(sub)}</div></div>"""


def bar(label, count, total, colour) -> str:
    pct = round(100 * count / total) if total else 0
    return f"""<div class="bar"><div class="lbl"><span>{esc(label)}</span>
      <span style="color:{colour}">{count}</span></div>
      <div class="track"><div class="fill" style="width:{max(pct, 3)}%;
      background:linear-gradient(90deg,{colour}55,{colour})"></div></div></div>"""


def donut(parts, size: int = 150) -> str:
    """Drawn with dash offsets, so it needs no chart library."""
    total = sum(n for _, n, _ in parts) or 1
    radius = size / 2 - 15
    circ = 2 * 3.14159 * radius
    offset, arcs = 0.0, []
    for _, count, colour in parts:
        length = circ * count / total
        arcs.append(f'<circle cx="{size/2}" cy="{size/2}" r="{radius}" fill="none" '
                    f'stroke="{colour}" stroke-width="15" stroke-linecap="butt" '
                    f'stroke-dasharray="{length:.1f} {circ - length:.1f}" '
                    f'stroke-dashoffset="{-offset:.1f}"/>')
        offset += length
    keys = "".join(f'<span><i style="width:9px;height:9px;border-radius:3px;background:{c};'
                   f'display:inline-block"></i>{esc(n)} {v}</span>' for n, v, c in parts)
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'style="transform:rotate(-90deg)">'
            f'<circle cx="{size/2}" cy="{size/2}" r="{radius}" fill="none" '
            f'stroke="rgba(255,255,255,.07)" stroke-width="15"/>{"".join(arcs)}</svg>'
            f'<div class="legend">{keys}</div>')


def phone(label: str, text: str, segments: int) -> str:
    """The message exactly as it lands on someone's handset."""
    return f"""<div class="phone"><div class="top"><span>SMS &middot; {esc(label)}</span>
      <span>{len(text)} chars</span></div>
      <div class="bubble">{esc(text)}</div>
      <div class="len">{segments} message part{"s" if segments != 1 else ""}</div></div>"""


def map_svg(located) -> str:
    """India, with a pulsing dot per alert. `located` is (lat, lon, colour, label)."""
    top, bottom, left, right = 37.6, 6.5, 67.5, 97.8
    w, h = 420, 470

    def xy(lat, lon):
        return (round((lon - left) / (right - left) * w, 1),
                round((top - lat) / (top - bottom) * h, 1))

    outline = " ".join(f"{x},{y}" for x, y in (xy(lat, lon) for lat, lon in INDIA))
    dots = []
    for i, (lat, lon, colour, label) in enumerate(located):
        x, y = xy(lat, lon)
        delay = round((i % 6) * 0.35, 2)
        dots.append(
            f'<circle cx="{x}" cy="{y}" r="4" fill="{colour}" opacity=".45">'
            f'<animate attributeName="r" values="4;17;4" dur="2.6s" begin="{delay}s" '
            f'repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values=".45;0;.45" dur="2.6s" begin="{delay}s" '
            f'repeatCount="indefinite"/></circle>'
            f'<circle cx="{x}" cy="{y}" r="4.5" fill="{colour}" filter="url(#glow)">'
            f'<title>{esc(label)}</title></circle>')
    return f"""<svg viewBox="0 0 {w} {h}" width="100%" role="img"
      aria-label="Map of current alerts across India">
      <defs>
        <linearGradient id="land" x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0%" stop-color="#0f2033"/><stop offset="100%" stop-color="#101a2e"/>
        </linearGradient>
        <filter id="glow"><feGaussianBlur stdDeviation="2.6" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      <polygon points="{outline}" fill="url(#land)" stroke="#22d3ee" stroke-opacity=".45"
        stroke-width="1.2"/>
      {"".join(dots)}</svg>"""


def sample_tag(text: str = "Sample data") -> str:
    """
    Marks the parts of a hosted copy that aren't real, and only those parts.

    The alerts are genuinely live, so they carry no label. Subscribers and
    delivery figures on the public copy are examples, and saying so quietly
    beside them beats a banner across every page.
    """
    return (f'<span style="font-size:10.5px;font-weight:700;letter-spacing:.12em;'
            f'text-transform:uppercase;color:var(--cyan);border:1px solid var(--edge);'
            f'border-radius:6px;padding:3px 8px;margin-left:10px;vertical-align:2px">'
            f'{esc(text)}</span>')


def ticker(items) -> str:
    """A slow scroll of what is live, so the page feels awake."""
    if not items:
        items = [("#22d3ee", "All quiet", "no live warnings right now")]
    run = "".join(f'<span><i class="sq" style="background:{c}"></i><b>{esc(t)}</b> {esc(d)}</span>'
                  for c, t, d in items)
    # Twice over, so the loop has no visible seam.
    return f'<div class="ticker"><div class="wrap"><div class="track">{run}{run}</div></div></div>'


def layout(active: str, eyebrow: str, headline: str, lede: str, body: str,
           token: str = "", aside: str = "", strip=None, demo: bool = False) -> str:
    def href(path: str) -> str:
        return f"/dashboard{path}" + (f"?token={token}" if token else "")

    nav = "".join(f'<a class="{"on" if path == active else ""}" href="{href(path)}">{label}</a>'
                  for path, label in NAV)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="90"><meta name="color-scheme" content="dark">
<title>CommBot control room</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap"
 rel="stylesheet">
<style>{STYLE}</style></head>
<body>
<div class="wrap"><div class="bar">
  <div class="logo"><i>{icon('shield', '#22d3ee', 17)}</i>CommBot</div>
  <nav class="nav">{nav}</nav>
</div></div>
<footer><div class="wrap">
  Alerts come from NDMA's SACHET platform, published by IMD, the Central Water Commission and
  state disaster management authorities. CommBot relays official warnings, it never issues its
  own. Boundary from DataMeet's open India map (CC-BY). Page refreshes every 90 seconds.
  {"<br>On this hosted copy the alerts are live, the subscribers are samples, and no SMS is sent from it." if demo else ""}
</div></footer>
{ticker(strip or [])}
<div class="wrap"><div class="hero">
  <div>
    <div class="eyebrow"><span class="pulse"></span>{esc(eyebrow)}</div>
    <h1>{esc(headline)}</h1>
    <p>{esc(lede)}</p>
  </div>
  {aside}
</div></div>
<main class="wrap">{body}</main>
<footer><div class="wrap">
  Alerts come from NDMA's SACHET platform, published by IMD, the Central Water Commission and
  state disaster management authorities. CommBot relays official warnings, it never issues its
  own. Boundary from DataMeet's open India map (CC-BY). Page refreshes every 90 seconds.
</div></footer>
</body></html>"""