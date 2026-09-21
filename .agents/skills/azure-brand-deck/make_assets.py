"""Generate Azure-brand decorative assets.

Run once per session before building a deck:

    python3 .agents/skills/azure-brand-deck/make_assets.py

Outputs PNGs into ./working/assets/ (relative to cwd, which should be the
workspace root so the pptxgenjs script can reference them as
"working/assets/<file>.png").

Produces:
  - ms_logo.png / ms_logo_white.png   — Microsoft 4-colour tile logo + wordmark
  - sphere_light.png                   — wireframe sphere on dark backgrounds
  - sphere_dark.png                    — wireframe sphere on light backgrounds
  - sphere_purple.png                  — purple wireframe sphere
  - capsules_light.png                 — diagonal capsule chain motif (light)
  - capsules_purple.png                — diagonal capsule chain motif (purple)
"""
import os

try:
    import cairosvg
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing Python dependency 'cairosvg'. Install it in the active environment "
        "with: python3 -m pip install cairosvg"
    ) from exc

OUT = os.path.join(os.getcwd(), "working", "assets")
os.makedirs(OUT, exist_ok=True)

# ---------- Microsoft 4-colour logo ----------
ms_logo_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 80">
<rect x="0" y="0" width="36" height="36" fill="#F25022"/>
<rect x="40" y="0" width="36" height="36" fill="#7FBA00"/>
<rect x="0" y="40" width="36" height="36" fill="#00A4EF"/>
<rect x="40" y="40" width="36" height="36" fill="#FFB900"/>
<text x="90" y="52" font-family="Segoe UI, Arial, sans-serif" font-size="36" font-weight="400" fill="#505050">Microsoft</text>
</svg>"""

with open(f"{OUT}/ms_logo.svg", "w") as f:
    f.write(ms_logo_svg)
cairosvg.svg2png(url=f"{OUT}/ms_logo.svg", write_to=f"{OUT}/ms_logo.png", output_width=800)

ms_logo_white_svg = ms_logo_svg.replace('fill="#505050"', 'fill="#FFFFFF"')
with open(f"{OUT}/ms_logo_white.svg", "w") as f:
    f.write(ms_logo_white_svg)
cairosvg.svg2png(url=f"{OUT}/ms_logo_white.svg", write_to=f"{OUT}/ms_logo_white.png", output_width=800)


# ---------- Wireframe sphere ----------
def sphere(stroke, sw=0.8):
    lines = []
    for r in [180, 165, 145, 120, 90, 55]:
        lines.append(
            f'<ellipse cx="200" cy="200" rx="{r}" ry="{r*0.35:.0f}" '
            f'fill="none" stroke="{stroke}" stroke-width="{sw}" opacity="0.85"/>'
        )
    for angle in range(0, 180, 18):
        lines.append(
            f'<ellipse cx="200" cy="200" rx="{180*0.35:.0f}" ry="180" '
            f'fill="none" stroke="{stroke}" stroke-width="{sw}" opacity="0.6" '
            f'transform="rotate({angle} 200 200)"/>'
        )
    lines.append(
        f'<circle cx="200" cy="200" r="180" fill="none" '
        f'stroke="{stroke}" stroke-width="{sw+0.4}" opacity="0.9"/>'
    )
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">' + "".join(lines) + "</svg>"


for name, stroke, sw in [
    ("sphere_light",  "#7FB3FF", 1.2),
    ("sphere_dark",   "#5D52EC", 1.0),
    ("sphere_purple", "#D59ED7", 1.0),
]:
    with open(f"{OUT}/{name}.svg", "w") as f:
        f.write(sphere(stroke, sw))
    cairosvg.svg2png(url=f"{OUT}/{name}.svg", write_to=f"{OUT}/{name}.png", output_width=1200)


# ---------- Capsule chain ----------
def capsules(stroke):
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800">']
    positions = [(120, 680), (220, 580), (320, 480), (420, 380), (520, 280), (620, 180), (720, 80)]
    for i, (x, y) in enumerate(positions):
        out.append(
            f'<g transform="translate({x} {y}) rotate(-45)">'
            f'<rect x="-40" y="-14" width="80" height="28" rx="14" ry="14" '
            f'fill="none" stroke="{stroke}" stroke-width="1.3" opacity="0.85"/></g>'
        )
        if i < len(positions) - 1:
            cx = (x + positions[i + 1][0]) / 2
            cy = (y + positions[i + 1][1]) / 2
            out.append(
                f'<circle cx="{cx}" cy="{cy}" r="8" fill="none" '
                f'stroke="{stroke}" stroke-width="1.2" opacity="0.75"/>'
            )
    out.append("</svg>")
    return "".join(out)


for name, stroke in [("capsules_light", "#7FB3FF"), ("capsules_purple", "#A78BE0")]:
    with open(f"{OUT}/{name}.svg", "w") as f:
        f.write(capsules(stroke))
    cairosvg.svg2png(url=f"{OUT}/{name}.svg", write_to=f"{OUT}/{name}.png", output_width=1400)


print(f"Wrote {len([f for f in os.listdir(OUT) if f.endswith('.png')])} PNGs to {OUT}")
