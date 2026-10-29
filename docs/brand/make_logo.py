"""Draw the Rumbo logo from its construction and write its SVG files.

The symbol is "r...o": the first letter, a dotted final leg for the work in
between (u, m, b), and the owner's fix -- a chart fix, ring and dot -- in place
of the o. The wordmark is a monoline geometric lowercase whose o is that fix.

    python3 docs/brand/make_logo.py

writes docs/brand/*.svg and the two plugin listing icons. Standard library only.
"""
import math
from pathlib import Path

INK, PAPER = '#12222e', '#fafcfc'
FIX, FIX_ON_DARK = '#c42a78', '#ef72b3'

def n(v):
    return ('%.2f' % v).rstrip('0').rstrip('.')

# Symbol construction, in design units with the r's stem foot at (0, 0).
W, R, STEM = 28, 38, 104         # r stroke, shoulder radius, stem length to the shoulder
DOT, PITCH = 13, 19              # leg dots: diameter and spacing (three: u, m, b)
RING, RING_W, PIP = 34, 19, 10   # fix ring radius and stroke, centre pip radius

def symbol(fg, fix, scale=1.0, dx=0.0, dy=0.0, dots=3):
    t = lambda x, y: (n(x*scale+dx), n(y*scale+dy))
    yt = -STEM - R                                   # course line through the shoulder
    arm = R
    out = []
    x0, y0 = t(0, 0); x1, y1 = t(0, -STEM); x2, y2 = t(arm, yt)
    out.append(f'<path d="M{x0} {y0}V{y1}A{n(R*scale)} {n(R*scale)} 0 0 1 {x2} {y2}" fill="none" stroke="{fg}" stroke-width="{n(W*scale)}" stroke-linecap="round"/>')
    x = arm + W/2 + (PITCH - DOT) + DOT/2 - 2
    for _ in range(dots):
        cx, cy = t(x, yt)
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{n(DOT/2*scale)}" fill="{fg}"/>')
        x += PITCH
    ring_x = x - PITCH + DOT/2 + (PITCH - DOT) + 2 + RING + RING_W/2
    cx, cy = t(ring_x, yt)
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{n(RING*scale)}" fill="none" stroke="{fix}" stroke-width="{n(RING_W*scale)}"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{n(PIP*scale)}" fill="{fix}"/>')
    bbox = (-W/2, yt - RING - RING_W/2, ring_x + RING + RING_W/2, W/2)
    return out, bbox

def tile(bg, fg, fix, size=256, content=184, nudge=(0, -2), dots=3, rx=56):
    _, (bx0, by0, bx1, by1) = symbol(fg, fix, dots=dots)
    s = content / (bx1 - bx0)
    dx = (size - (bx1 - bx0)*s)/2 - bx0*s + nudge[0]
    dy = (size - (by1 - by0)*s)/2 - by0*s + nudge[1]
    body, _ = symbol(fg, fix, s, dx, dy, dots)
    rect = [f'<rect width="{size}" height="{size}" rx="{rx}" fill="{bg}"/>'] if bg else []
    return svg(f'0 0 {size} {size}', rect + body, 'Rumbo', size, size)

# Wordmark construction: monoline geometric lowercase, x-height 100, baseline y=0.
XH, WW, ASC, RM = 100, 20, 150, 34
SPACE = dict(ru=14, um=24, mb=24, bo=16)

def wordmark_parts(fg, fix, ox=0.0, oy=0.0, k=1.0):
    h = WW/2; r = (XH - WW)/2; cy = -h - r; top = -XH + h; cym = top + RM
    P = lambda x, y: f'{n(x*k+ox)} {n(y*k+oy)}'
    L = lambda v: n(v*k)
    out = []
    def stroke(d, color=fg):
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{L(WW)}" stroke-linecap="round"/>')
    x = h
    a = math.radians(300); ex, ey = x + r + r*math.cos(a), cy + r*math.sin(a)
    stroke(f'M{P(x,0)}V{n(top*k+oy)}M{P(x,cy)}A{L(r)} {L(r)} 0 0 1 {P(ex,ey)}')                     # r
    x = ex + h + SPACE['ru'] + h
    stroke(f'M{P(x,top)}V{n(cy*k+oy)}A{L(r)} {L(r)} 0 0 0 {P(x+2*r,cy)}M{P(x+2*r,top)}V{n(oy)}')  # u
    x += 2*r + WW + SPACE['um']
    stroke(f'M{P(x,0)}V{n(top*k+oy)}M{P(x,cym)}A{L(RM)} {L(RM)} 0 0 1 {P(x+2*RM,cym)}V{n(oy)}'
           f'M{P(x+2*RM,cym)}A{L(RM)} {L(RM)} 0 0 1 {P(x+4*RM,cym)}V{n(oy)}')                       # m
    x += 4*RM + WW + SPACE['mb']
    stroke(f'M{P(x,-ASC+h)}V{n(oy)}')                                                                # b
    out.append(f'<circle cx="{n((x+r)*k+ox)}" cy="{n(cy*k+oy)}" r="{L(r)}" fill="none" stroke="{fg}" stroke-width="{L(WW)}"/>')
    x += 2*r + WW + SPACE['bo'] + r
    out.append(f'<circle cx="{n(x*k+ox)}" cy="{n(cy*k+oy)}" r="{L(r)}" fill="none" stroke="{fix}" stroke-width="{L(WW)}"/>')
    out.append(f'<circle cx="{n(x*k+ox)}" cy="{n(cy*k+oy)}" r="{L(WW*0.6)}" fill="{fix}"/>')   # o: the fix
    return out, x + r + h

def wordmark(fg, fix):
    pad = 4
    body, width = wordmark_parts(fg, fix, ox=pad, oy=ASC + pad)
    return svg(f'0 0 {n(width + 2*pad)} {ASC + WW/2 + 2*pad}', body, 'rumbo', width + 2*pad, ASC + WW/2 + 2*pad)

def svg(viewbox, parts, title, w, h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" width="{n(w)}" height="{n(h)}" role="img">'
            f'<title>{title}</title>' + ''.join(parts) + '</svg>\n')

FILES = {
    'rumbo-symbol.svg': lambda: tile(INK, PAPER, FIX_ON_DARK),
    'rumbo-symbol-light.svg': lambda: tile(PAPER, INK, FIX),
    'rumbo-symbol-mono.svg': lambda: tile(None, 'currentColor', 'currentColor', content=232, nudge=(0, 0)),
    'rumbo-symbol-small.svg': lambda: tile(INK, PAPER, FIX_ON_DARK, dots=1, content=176),
    'rumbo-wordmark.svg': lambda: wordmark(INK, FIX),
    'rumbo-wordmark-reversed.svg': lambda: wordmark(PAPER, FIX_ON_DARK),
}

# The plugin listings use the app icon.
ICONS = ['rumbo/.claude-plugin/icon.svg', 'openai-plugin/rumbo/assets/icon.svg']

if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    for name, make in FILES.items():
        (here / name).write_text(make())
        print(here / name)
    for icon in ICONS:
        (here.parents[1] / icon).write_text(FILES['rumbo-symbol.svg']())
        print(here.parents[1] / icon)
