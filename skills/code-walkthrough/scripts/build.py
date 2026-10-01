#!/usr/bin/env python3
"""Render a code-walkthrough page from a compact JSON spec.

The spec holds only anchors and explanations; the code itself is read from disk here, so the
model never has to reproduce source text. Usage:

    build.py SPEC.json [-o OUT.html]

Exit code 1 with a list of every bad anchor when something does not resolve.
"""
import hashlib
import html
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"

LABELS = {
    "tr": {
        "request": "Ne gönderiyoruz · request",
        "response": "Ne alıyoruz · response",
        "behind": "Arkada ne oluyor",
        "behind_hint": "Numaralar aşağıdaki kod notlarındaki numaralarla aynı. Düz çizgi çağrı, kesikli çizgi dönen değer.",
        "read_code": "Kodu sırayla oku",
        "models": "Model sınıfları",
        "models_hint": "Bu akışta taşınan request, response ve entity sınıfları.",
        "new": "yeni",
        "modified": "değişti",
        "unchanged": "değişmedi",
        "deleted_lines": "satır silindi",
        "legend": "Yeşil çizgili satırlar bu diffte eklendi ya da değişti. Satır numarasının yanındaki kırmızı üçgen, o satırın altında satır silindiğini gösterir; üzerine gelince kaç satır olduğu görünür.",
        "before": "Önce",
        "after": "Sonra",
    },
    "en": {
        "request": "What we send · request",
        "response": "What we get · response",
        "behind": "What happens behind it",
        "behind_hint": "The numbers match the numbers on the code notes below. Solid line is a call, dashed line a return value.",
        "read_code": "Read the code in order",
        "models": "Model classes",
        "models_hint": "Request, response and entity classes carried through this flow.",
        "new": "new",
        "modified": "changed",
        "unchanged": "unchanged",
        "deleted_lines": "lines deleted",
        "legend": "Lines with a green bar were added or changed in this diff. A small red triangle by the line number marks lines deleted just below; hover it for the count.",
        "before": "Before",
        "after": "After",
    },
}


def esc(s):
    return html.escape(str(s), quote=False)


def md(s):
    s = esc(s or "")
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)


# ------------------------------------------------------------------ highlighting
KW = set(
    """abstract boolean break case catch char class const continue def default do double elif else
    enum export extends final finally float for fun from function if implements import in
    instanceof int interface is lambda let long new None not null or package pass private protected
    public raise record return self static struct super switch this throw throws try type val var
    void when while with yield true false True False async await override sealed data object""".split()
)
C_LIKE = re.compile(
    r'(?P<str>"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\])*`)|(?P<chr>\'(?:\\.|[^\'\\])*\')|(?P<com>//.*)'
    r"|(?P<bstart>/\*)|(?P<ann>@\w+)|(?P<num>\b\d+[LlFf]?\b)|(?P<word>\b[A-Za-z_]\w*\b)"
)
HASH_LIKE = re.compile(
    r'(?P<str>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|(?P<com>#.*)|(?P<ann>@\w+)'
    r"|(?P<num>\b\d+\b)|(?P<word>\b[A-Za-z_]\w*\b)"
)
HASH_EXT = {".py", ".yml", ".yaml", ".properties", ".sh", ".rb", ".toml", ".env", ".example"}
MARKUP_EXT = {".html", ".xml", ".vue", ".svelte", ".xhtml"}


def hl_code(lines, token):
    out, in_block = [], False
    for raw in lines:
        res, i = [], 0
        if in_block:
            end = raw.find("*/")
            if end < 0:
                out.append(f'<span class="c">{esc(raw)}</span>')
                continue
            res.append(f'<span class="c">{esc(raw[: end + 2])}</span>')
            i, in_block = end + 2, False
        while i < len(raw):
            m = token.search(raw, i)
            if not m:
                res.append(esc(raw[i:]))
                break
            res.append(esc(raw[i : m.start()]))
            kind, text = m.lastgroup, m.group()
            if kind == "bstart":
                end = raw.find("*/", m.end())
                if end < 0:
                    res.append(f'<span class="c">{esc(raw[m.start():])}</span>')
                    in_block = True
                    break
                res.append(f'<span class="c">{esc(raw[m.start():end + 2])}</span>')
                i = end + 2
                continue
            cls = {"str": "s", "chr": "s", "com": "c", "ann": "a", "num": "n"}.get(kind)
            if kind == "word":
                cls = "k" if text in KW else ("t" if text[0].isupper() else None)
            res.append(f'<span class="{cls}">{esc(text)}</span>' if cls else esc(text))
            i = m.end()
        out.append("".join(res))
    return out


def hl_markup(lines):
    out = []
    for raw in lines:
        s = esc(raw)
        s = re.sub(r'("[^"]*")', r'<span class="s">\1</span>', s)
        s = re.sub(r"(&lt;/?[a-zA-Z!][^&\s]*)", r'<span class="k">\1</span>', s)
        s = re.sub(r"(\{\{\s*[\w.]+\s*\}\})", r'<span class="a">\1</span>', s)
        out.append(s)
    return out


def highlight(path, lines):
    ext = path.suffix.lower()
    if ext in MARKUP_EXT:
        return hl_markup(lines)
    if ext in HASH_EXT or path.name.startswith(".env"):
        return hl_code(lines, HASH_LIKE)
    return hl_code(lines, C_LIKE)


# ------------------------------------------------------------------ git
_git_cache = {}


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def toplevel(path):
    d = str(path.parent)
    if d not in _git_cache:
        _git_cache[d] = git(d, "rev-parse", "--show-toplevel").strip() or None
    return _git_cache[d]


def file_diff(path, base):
    """-> (status, added_line_set, {line_after_which_deleted: count})"""
    top = toplevel(path)
    if not top:
        return "unchanged", set(), {}
    rel = str(path.relative_to(top))
    st = git(top, "status", "--porcelain", "--", rel)
    if st.startswith("??"):
        return "new", set(range(1, 10**7)), {}
    out = git(top, "diff", "-U0", base, "--", rel)
    if not out:
        return "unchanged", set(), {}
    if "\nnew file mode" in out or out.startswith("new file mode"):
        return "new", set(range(1, 10**7)), {}
    added, deleted = set(), {}
    for m in re.finditer(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", out, re.M):
        old_n = int(m.group(1) or 1)
        start, new_n = int(m.group(2)), int(m.group(3) or 1)
        if new_n:
            added.update(range(start, start + new_n))
        if old_n > new_n:
            at = start + new_n - 1 if new_n else start
            deleted[at] = deleted.get(at, 0) + old_n - new_n
    return "modified", added, deleted


# ------------------------------------------------------------------ panels
errors = []
manifest = {}


def resolve_panel(p, spec, base_dir):
    root = spec.get("roots", {}).get(p.get("root"), spec.get("repo", "."))
    path = (base_dir / root / p["path"]).resolve()
    if not path.is_file():
        errors.append(f"file not found: {path}")
        return None
    src = path.read_text(encoding="utf-8", errors="replace").rstrip("\n").split("\n")
    manifest[str(path)] = hashlib.sha1("\n".join(src).encode()).hexdigest()
    notes = []
    for n in p.get("notes", []):
        at, text = n[0], n[1]
        step = n[2] if len(n) > 2 else None
        span = n[3] if len(n) > 3 else 1
        if isinstance(at, int):
            line = at if 1 <= at <= len(src) else None
        else:
            find, nth = (at[0], at[1]) if isinstance(at, list) else (at, 1)
            hits = [i + 1 for i, l in enumerate(src) if find in l]
            line = hits[nth - 1] if len(hits) >= nth else None
        if line is None:
            errors.append(f"{p['path']}: anchor not found: {at!r}")
            continue
        notes.append({"line": line, "span": max(1, span), "step": step, "text": text})
    notes.sort(key=lambda r: r["line"])
    status, added, deleted = file_diff(path, spec.get("base", "HEAD"))
    if p.get("root") and status == "unchanged" and p.get("libLabel"):
        status = "lib"
    return {
        "name": path.name,
        "display": p.get("label") or p["path"],
        "role": p.get("role", ""),
        "status": status,
        "lines": highlight(path, src),
        "added": added,
        "deleted": deleted,
        "notes": notes,
        "lib": p.get("libLabel"),
    }


def render_panel(p, anchor_id, ordinal, L):
    hl = {}
    for k, n in enumerate(p["notes"]):
        for ln in range(n["line"], n["line"] + n["span"]):
            hl.setdefault(ln, k)
    starts = {}
    for k, n in enumerate(p["notes"]):
        starts.setdefault(n["line"], []).append(k)

    def badge(n):
        return f'<span class="step">{esc(n["step"])}</span>' if n["step"] else '<span class="step dot"></span>'

    all_new = p["status"] == "new"
    rows = []
    for i, code in enumerate(p["lines"], start=1):
        cls = ["ln"]
        attrs = ""
        if i in hl:
            cls.append("hl")
            attrs = f' data-note="{hl[i]}"'
        if not all_new and i in p["added"]:
            cls.append("add")
        if i in p["deleted"]:
            cls.append("del")
            attrs += f' title="{p["deleted"][i]} {esc(L["deleted_lines"])}"'
        rows.append(
            f'<div class="{" ".join(cls)}" data-n="{i}"{attrs}><span class="no">{i}</span>'
            f'<span class="tx">{code or " "}</span></div>'
        )
        for k in starts.get(i, []):
            n = p["notes"][k]
            rows.append(f'<div class="inote" data-note="{k}">{badge(n)}<p>{md(n["text"])}</p></div>')
    notes = "".join(
        f'<aside class="note" data-note="{k}" data-line="{n["line"]}">{badge(n)}<p>{md(n["text"])}</p></aside>'
        for k, n in enumerate(p["notes"])
    )
    st = p["status"]
    st_text = p["lib"] if st == "lib" else L.get({"new": "new", "modified": "modified"}.get(st, "unchanged"))
    st_cls = {"new": "new", "modified": "mod"}.get(st, "lib")
    return f"""
<section class="file" id="{anchor_id}">
  <header class="file-head">
    <span class="ord">{ordinal}</span>
    <div class="fh-text">
      <div class="fname"><b>{esc(p["name"])}</b> <span class="badge {st_cls}">{esc(st_text)}</span></div>
      <div class="fpath">{esc(p["display"])}</div>
      <div class="frole">{md(p["role"])}</div>
    </div>
  </header>
  <div class="cw">
    <div class="code">{"".join(rows)}</div>
    <div class="notes">{notes}</div>
    <svg class="wires" aria-hidden="true"></svg>
  </div>
</section>"""


# ------------------------------------------------------------------ sequence diagram
def seq_svg(actors, msgs):
    col, top, row = 150, 70, 46
    w = col * len(actors) + 20
    h = top + row * len(msgs) + 40
    pos = {a[0]: 10 + col * i + col // 2 for i, a in enumerate(actors)}
    parts = [
        f'<svg class="seq" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">'
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="ahc"/></marker>'
        '<marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="ahr"/></marker></defs>'
    ]
    for a in actors:
        key, label, sub = a[0], a[1], a[2] if len(a) > 2 else ""
        x = pos[key]
        parts.append(f'<line x1="{x}" y1="{top - 14}" x2="{x}" y2="{h - 12}" class="life"/>')
        parts.append(f'<rect x="{x - 68}" y="6" width="136" height="44" rx="6" class="actor"/>')
        parts.append(f'<text x="{x}" y="25" class="al">{esc(label)}</text>')
        parts.append(f'<text x="{x}" y="41" class="as">{esc(sub)}</text>')
    for i, m in enumerate(msgs):
        a, b, label = m[0], m[1], m[2]
        kind = m[3] if len(m) > 3 else "call"
        step = m[4] if len(m) > 4 else None
        if a not in pos or b not in pos:
            errors.append(f"sequence message references unknown actor: {m!r}")
            continue
        y = top + row * i + 18
        x1, x2 = pos[a], pos[b]
        if a == b:
            parts.append(f'<path d="M{x1},{y - 8} h34 v16 h-30" class="msg call" marker-end="url(#ah)"/>')
            tx, anchor = x1 + 42, "start"
        else:
            cls, mk = ("ret", "ahr") if kind == "ret" else ("call", "ah")
            d = 1 if x2 > x1 else -1
            parts.append(
                f'<line x1="{x1 + 4 * d}" y1="{y}" x2="{x2 - 4 * d}" y2="{y}" class="msg {cls}" marker-end="url(#{mk})"/>'
            )
            tx, anchor = (x1 + x2) / 2, "middle"
        if step is not None:
            tw = len(label) * 6.9
            cx = tx - tw / 2 - 13 if anchor == "middle" else tx + tw + 12
            parts.append(
                f'<circle cx="{cx}" cy="{y - 11}" r="9" class="sc"/><text x="{cx}" y="{y - 7.5}" class="sn">{esc(step)}</text>'
            )
        parts.append(f'<text x="{tx}" y="{y - 7}" text-anchor="{anchor}" class="ml {kind}">{esc(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------ sections
def blocks_html(blocks):
    """Free blocks: {h}, {p}, {warn}, {cards:[[h,p]]}, {mermaid}, {html}."""
    out = []
    for b in blocks or []:
        if "h" in b:
            out.append(f"<h3>{md(b['h'])}</h3>")
        if "p" in b:
            out.append(f'<p class="lead">{md(b["p"])}</p>')
        if "mermaid" in b:
            out.append(f'<div class="seq-wrap"><pre class="mermaid">{esc(b["mermaid"])}</pre></div>')
        if "warn" in b:
            out.append(f'<div class="warn">{md(b["warn"])}</div>')
        if "cards" in b:
            cards = "".join(f'<div class="card2"><h4>{md(h)}</h4><p>{md(p)}</p></div>' for h, p in b["cards"])
            out.append(f'<div class="cards">{cards}</div>')
        if "html" in b:
            out.append(b["html"])
    return "".join(out)


def flow_html(f, idx, first, spec, base_dir, L):
    color = f"var(--c{f.get('color', idx) % 6})"
    parts = []
    if f.get("url"):
        verb = f'<span class="verb">{esc(f["method"])}</span>' if f.get("method") else ""
        parts.append(f'<div class="endpoint">{verb}<code>{esc(f["url"])}</code></div>')
    if f.get("who"):
        parts.append(f'<p class="who">{md(f["who"])}</p>')
    if f.get("lead"):
        parts.append(f'<p class="lead">{md(f["lead"])}</p>')
    if f.get("request") or f.get("response"):
        alts = "".join(f"<li><b>{esc(k)}</b><span>{md(v)}</span></li>" for k, v in f.get("alts", []))
        alts_html = f'<ul class="alts">{alts}</ul>' if alts else ""
        parts.append(
            f'<div class="io"><div class="io-card"><div class="io-label">{esc(L["request"])}</div>'
            f'<pre>{esc(f.get("request", ""))}</pre></div><div class="io-arrow" aria-hidden="true">→</div>'
            f'<div class="io-card"><div class="io-label">{esc(L["response"])}</div><pre>{esc(f.get("response", ""))}</pre>'
            f'{alts_html}</div></div>'
        )
    parts.append(blocks_html(f.get("blocks")))
    if f.get("actors") and f.get("msgs"):
        parts.append(
            f'<h3>{esc(L["behind"])}</h3><p class="hint">{esc(L["behind_hint"])}</p>'
            f'<div class="seq-wrap">{seq_svg(f["actors"], f["msgs"])}</div>'
        )
    code = [p for p in (resolve_panel(x, spec, base_dir) for x in f.get("panels", [])) if p]
    models = [p for p in (resolve_panel(x, spec, base_dir) for x in f.get("models", [])) if p]
    if code or models:
        toc = "".join(
            f'<a href="#{f["id"]}-f{i + 1}"><span>{i + 1}</span>{esc(p["name"])}</a>' for i, p in enumerate(code)
        )
        toc += "".join(
            f'<a class="m" href="#{f["id"]}-m{i + 1}"><span>M{i + 1}</span>{esc(p["name"])}</a>'
            for i, p in enumerate(models)
        )
        parts.append(f'<h3>{esc(L["read_code"])}</h3><p class="hint">{esc(L["legend"])}</p><nav class="toc">{toc}</nav>')
        parts += [render_panel(p, f'{f["id"]}-f{i + 1}', i + 1, L) for i, p in enumerate(code)]
        if models:
            parts.append(f'<h3>{esc(L["models"])}</h3><p class="hint">{esc(L["models_hint"])}</p>')
            parts += [render_panel(p, f'{f["id"]}-m{i + 1}', f"M{i + 1}", L) for i, p in enumerate(models)]
    hidden = "" if first else " hidden"
    return (
        f'<div class="flow" id="flow-{f["id"]}" role="tabpanel" aria-labelledby="tab-{f["id"]}" '
        f'style="--flow:{color}"{hidden}>{"".join(parts)}</div>'
    )


def tab_method(f):
    return f'<span class="tab-m">{esc(f["method"])}</span>' if f.get("method") else ""


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    spec_path = Path(args[0]).resolve()
    out = Path(args[args.index("-o") + 1]) if "-o" in args else spec_path.with_suffix(".html")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    base_dir = spec_path.parent
    lang = spec.get("lang", "en")
    L = {**LABELS["en"], **LABELS.get(lang, {}), **spec.get("labels", {})}
    flows = spec.get("flows", [])

    tabs = "".join(
        f'<button class="tab" role="tab" id="tab-{f["id"]}" aria-controls="flow-{f["id"]}" '
        f'aria-selected="{"true" if i == 0 else "false"}" data-flow="{f["id"]}" '
        f'style="--flow:var(--c{f.get("color", i) % 6})">'
        f'{tab_method(f)}{esc(f["tab"])}</button>'
        for i, f in enumerate(flows)
    )
    body = "".join(flow_html(f, i, i == 0, spec, base_dir, L) for i, f in enumerate(flows))

    ba = ""
    if spec.get("before") or spec.get("after"):
        ba = (
            f'<div class="ba"><div><div class="ba-h">{esc(L["before"])}</div><p>{md(spec.get("before"))}</p></div>'
            f'<div><div class="ba-h">{esc(L["after"])}</div><p>{md(spec.get("after"))}</p></div></div>'
        )
    overview = (
        f'<div class="seq-wrap"><pre class="mermaid">{esc(spec["overview"])}</pre></div>' if spec.get("overview") else ""
    )
    if errors:
        print("Spec errors:\n  " + "\n  ".join(errors), file=sys.stderr)
        sys.exit(1)

    css = (ASSETS / "page.css").read_text(encoding="utf-8")
    js = (ASSETS / "page.js").read_text(encoding="utf-8")
    page = f"""<title>{esc(spec.get("pageTitle", spec.get("title", "Code walkthrough")))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{css}</style>
<div class="page" lang="{esc(lang)}">
  <header class="top">
    <div class="eyebrow">{esc(spec.get("eyebrow", ""))}</div>
    <h1>{esc(spec.get("title", ""))}</h1>
    <p class="sub">{md(spec.get("subtitle", ""))}</p>
    {ba}{overview}
  </header>
  <nav class="tabs" role="tablist">{tabs}</nav>
  {body}
</div>
<script>{js}</script>
"""
    out.write_text(page, encoding="utf-8")
    prev = out.with_suffix(".manifest.json")
    old = json.loads(prev.read_text()) if prev.exists() else {}
    changed = [p for p, h in manifest.items() if p in old and old[p] != h]
    prev.write_text(json.dumps(manifest, indent=0))
    print(f"wrote {out} ({len(page) // 1024} KB, {len(manifest)} files)")
    if changed:
        print("source changed since last build (check these notes):\n  " + "\n  ".join(changed))


if __name__ == "__main__":
    main()
