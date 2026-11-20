"""TenderWin email design system, ported to Python for the outreach sender.

Source of truth: ~/AutoClaw/deploys/tenderwin-email-template/emails/brand.jsx (v2, 2026-10-02) and
the live copies in the bidcheck-au repo. Kept as plain table-based HTML because the sender builds
strings, not React; every token, size and rhythm matches brand.jsx so a cold email looks like the
product mail.

Differences from brand.jsx, and why:
  - the footer identifies Melbourne VIC (owner order 2026-11-19), not the template's placeholder;
  - there is no unsubscribe URL: a cold email's exit is a reply, so the note carries it;
  - the sign-off names the persona (owner order), where product mail signs "The TenderWin team".
"""

BLUE = "#024FF5"
INK = "#0B0F1C"
INK2 = "#3A3D45"
GREY = "#6B6E76"
QUIET = "#8A8D95"
HAIR = "#E7E5DF"
PAPER = "#FFFEFA"
SURFACE = "#F4F3EF"
AMBER = "#8A5A00"
WHITE = "#FFFFFF"

FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MEDIA = "https://tenderwin.com.au/brand/"
LOGO = MEDIA + "logo-email.png"
LOGO_DARK = MEDIA + "logo-email-dark.png"
TRUST_LINE = "Built on official Department of Finance AusTender data."

HEAD = f"font-family:{FONT};font-size:28px;line-height:35px;font-weight:500;letter-spacing:-0.03em;"

DARK_CSS = """
  :root { color-scheme: light dark; supported-color-schemes: light dark; }
  @media (max-width: 620px) {
    .bc-wrap { padding-left: 22px !important; padding-right: 22px !important; }
    .bc-h1, .bc-quiet { font-size: 25px !important; line-height: 31px !important; }
  }
  @media (prefers-color-scheme: dark) {
    .bc-paper { background-color: #0E1117 !important; }
    .bc-ink { color: #F2F1EC !important; }
    .bc-ink2 { color: #C9CBD1 !important; }
    .bc-grey, .bc-quiet { color: #858892 !important; }
    .bc-tile { background-color: #171B23 !important; }
    .bc-hair { border-color: #262A33 !important; }
    .bc-link { color: #6E98FF !important; }
    .bc-amber { color: #E0B45C !important; }
    .bc-logo-l { display: none !important; }
    .bc-logo-d { display: block !important; max-height: none !important; }
  }
"""


def esc(s):
    import html as _h
    return _h.escape(str(s or ""))


def eyebrow(text):
    """Quiet grey first line of the two-tone headline; brand.jsx closes it with a full stop."""
    t = str(text or "").strip()
    if t and t[-1].isalnum():
        t += "."
    return f'<p class="bc-quiet" style="{HEAD}margin:0;color:{QUIET}">{esc(t)}</p>'


def h1(text):
    t = str(text or "").strip()
    if t and t[-1].isalnum():
        t += "."
    return f'<h1 class="bc-ink" style="{HEAD}margin:0 0 18px;color:{INK}">{esc(t)}</h1>'


def p(html_text, mb=18):
    return (f'<p class="bc-ink2" style="margin:0 0 {mb}px;font-family:{FONT};font-size:16px;'
            f'line-height:26px;color:{INK2}">{html_text}</p>')


def b(text):
    return f'<strong class="bc-ink" style="font-weight:600;color:{INK}">{esc(text)}</strong>'


def small(text, mt=0):
    return (f'<p class="bc-grey" style="margin:{mt}px 0 0;font-family:{FONT};font-size:13px;'
            f'line-height:20px;color:{GREY}">{esc(text)}</p>')


def kv(rows, mt=4, mb=26):
    """Soft tile with hairline key/value rows (brand.jsx KeyValue)."""
    out = []
    for i, (k, v) in enumerate(rows):
        top = f"border-top:1px solid {HAIR};" if i else ""
        out.append(
            f'<tr>'
            f'<td class="bc-grey bc-hair" style="{top}padding:13px 0;font-family:{FONT};font-size:14px;'
            f'line-height:20px;color:{GREY};width:42%;vertical-align:top">{esc(k)}</td>'
            f'<td class="bc-ink bc-hair" style="{top}padding:13px 0;text-align:right;font-family:{FONT};'
            f'font-size:14px;line-height:20px;font-weight:600;color:{INK};vertical-align:top">{v}</td>'
            f'</tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'class="bc-tile" style="background-color:{SURFACE};border-radius:12px;'
            f'margin:{mt}px 0 {mb}px"><tr><td style="padding:4px 22px">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
            f'{"".join(out)}</table></td></tr></table>')


def cta(href, label, mt=8):
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:{mt}px 0 0">'
            f'<tr><td style="background-color:{BLUE};border-radius:999px">'
            f'<a href="{esc(href)}" style="display:inline-block;padding:13px 26px;font-family:{FONT};'
            f'font-weight:600;font-size:15px;line-height:20px;color:{WHITE};text-decoration:none">'
            f'{esc(label)}</a></td></tr></table>')


def spacer(h=18):
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:{h}px 0 0">'
            f'<tr><td style="height:1px;line-height:1px;font-size:1px">&nbsp;</td></tr></table>')


def divider(mt=28):
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="margin:{mt}px 0 0"><tr><td class="bc-hair" '
            f'style="border-top:1px solid {HAIR};height:1px;line-height:1px;font-size:1px">&nbsp;</td></tr></table>')


def signoff(name, line="Reply to this email any time, it comes to me."):
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:30px 0 0">'
            f'<tr><td><p class="bc-ink2" style="margin:0;font-family:{FONT};font-size:15px;'
            f'line-height:24px;color:{INK2}">{esc(line)}</p>'
            f'<p class="bc-ink" style="margin:14px 0 0;font-family:{FONT};font-size:15px;'
            f'line-height:22px;font-weight:600;color:{INK}">{esc(name)}<br>'
            f'<span style="font-weight:400;color:{GREY}">TenderWin</span></p></td></tr></table>')


def footer(postal, note=None):
    n = (f'<p class="bc-grey" style="margin:0 0 4px;font-family:{FONT};font-size:12px;'
         f'line-height:19px;color:{GREY}">{esc(note)}</p>') if note else ""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'class="bc-hair" style="border-top:1px solid {HAIR};margin:40px 0 0">'
            f'<tr><td style="padding:22px 0 0">{n}'
            f'<p class="bc-grey" style="margin:0;font-family:{FONT};font-size:12px;line-height:19px;color:{GREY}">'
            f'{esc(TRUST_LINE)} TenderWin, {esc(postal)}.</p></td></tr></table>')


def shell(preview, body_html, postal, note=None):
    """Html/Head/Body/Container + logo header, one 600px sheet of paper."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<style>{DARK_CSS}</style></head>'
        f'<body class="bc-paper" style="background-color:{PAPER};margin:0;padding:0;'
        f'font-family:{FONT};-webkit-font-smoothing:antialiased">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{esc(preview)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'class="bc-paper" style="background-color:{PAPER};margin:0;padding:0"><tr><td align="center">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" class="bc-wrap" '
        f'style="max-width:600px;width:100%;padding:44px 32px 48px">'
        f'<tr><td>'
        f'<img class="bc-logo-l" src="{LOGO}" width="134" height="24" alt="TenderWin" '
        f'style="display:block;border:0;outline:none">'
        f'<img class="bc-logo-d" src="{LOGO_DARK}" width="134" height="24" alt="TenderWin" '
        f'style="display:none;max-height:0;overflow:hidden;border:0;outline:none">'
        f'</td></tr>'
        f'<tr><td style="padding:36px 0 0">{body_html}</td></tr>'
        f'<tr><td>{footer(postal, note)}</td></tr>'
        f'</table></td></tr></table></body></html>')
