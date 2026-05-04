from __future__ import annotations
import hashlib

def svg_logo(idea_name: str) -> str:
    # deterministic color from hash; no external deps
    h = hashlib.sha1(idea_name.encode()).hexdigest()
    c1 = "#" + h[:6]
    c2 = "#" + h[6:12]
    initials = "".join([w[0].upper() for w in idea_name.split()[:2]])[:2] or "AI"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{c1}"/>
      <stop offset="1" stop-color="{c2}"/>
    </linearGradient>
  </defs>
  <rect x="48" y="48" width="416" height="416" rx="96" fill="url(#g)"/>
  <circle cx="256" cy="200" r="64" fill="rgba(255,255,255,0.18)"/>
  <path d="M160 352c20-56 64-88 96-88s76 32 96 88" fill="rgba(255,255,255,0.18)"/>
  <text x="256" y="430" text-anchor="middle" font-family="ui-sans-serif, system-ui" font-size="72" font-weight="800" fill="white">{initials}</text>
</svg>"""
