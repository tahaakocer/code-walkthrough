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
        "old_version": "Bu diffte silinen ya da değiştirilen satırların eski hali",
        "rail_title": "Çalışma sırası",
        "rail_hint": "Adıma tıkla, koda git. n / p ile adım adım ilerle.",
        "rail_toggle": "Akış",
        "rail_diagram": "sadece diyagramda",
        "legend": "Yeşil çizgili satırlar bu diffte eklendi ya da değişti. Satır numarasının yanındaki kırmızı üçgen, oradan satır silindiğini ya da değiştirildiğini gösterir: üzerine gelince eski hali görünür, tıklayınca kodun içinde açılır.",
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
        "old_version": "What these lines were before this diff",
        "rail_title": "Execution order",
        "rail_hint": "Click a step to jump to its code. n / p to step through.",
        "rail_toggle": "Flow",
        "rail_diagram": "diagram only",
        "legend": "Lines with a green bar were added or changed in this diff. A small red triangle by the line number marks lines deleted or replaced there: hover it to see the old version, click it to open it inline.",
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
C_KW = set(
    """abstract boolean break byte case catch char class const continue default do double else enum
    extends final finally float for goto if implements import instanceof int interface long native
    new null package permits private protected public record return sealed short static strictfp
    super switch synchronized this throw throws transient try var void volatile while yield true
    false non-sealed""".split()
)
KW_BY_EXT = {
    ".kt": {"fun", "val", "when", "is", "in", "object", "data", "override", "suspend", "internal",
            "open", "companion", "lateinit", "typealias", "by", "init", "as"},
    ".ts": {"function", "let", "export", "from", "type", "async", "await", "in", "of", "as",
            "declare", "readonly", "keyof", "undefined", "typeof", "delete"},
    ".py": {"def", "elif", "lambda", "None", "True", "False", "pass", "raise", "with", "from", "in",
            "is", "not", "or", "and", "as", "async", "await", "global", "nonlocal", "del", "assert",
            "except", "self"},
}
for _e in (".js", ".jsx", ".tsx", ".mjs", ".vue", ".svelte"):
    KW_BY_EXT[_e] = KW_BY_EXT[".ts"]
KW_BY_EXT[".kts"] = KW_BY_EXT[".kt"]
KW = C_KW  # rebound per file in highlight()
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


FIELD_DECL = re.compile(
    r"^\s*(?:(?:private|protected|public|static|final|volatile|transient|readonly|val|var|let|const)\s+)+"
    r"(?:[\w<>\[\], ?.]+\s+)?(\w+)\s*(?:[;=:]|$)"
)
METHOD_DECL = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|protected|private|static|final|abstract|synchronized|default|"
    r"native|override|suspend|async|export|fun|def|function)\s+)*(?:<[^>]+>\s+)?[\w<>\[\], ?.]*?\b(\w+)\s*\("
)
NOT_DECL = re.compile(r"^\s*(?:return|if|for|while|switch|catch|throw|new|else|case|try|do)\b|^\s*[\w.]+\s*\(|=")


def _comment(text, doc):
    """Comment span; Javadoc/KDoc/JSDoc tags get their own colour, as in IntelliJ."""
    body = esc(text)
    if doc:
        body = re.sub(r"(\{?@\w+)", r'<span class="jt">\1</span>', body)
    return f'<span class="{"d" if doc else "c"}">{body}</span>'


def hl_code(lines, token):
    fields, statics = set(), set()
    for raw in lines:
        m = FIELD_DECL.match(raw)
        if m and "(" not in raw.split("=")[0]:
            fields.add(m.group(1))
        d = METHOD_DECL.match(raw)
        if d and re.search(r"\bstatic\b", raw.split("(")[0]) and not NOT_DECL.match(raw):
            statics.add(d.group(1))
    out, in_block, doc = [], False, False
    for raw in lines:
        res, i = [], 0
        decl = METHOD_DECL.match(raw)
        decl_name = decl.group(1) if decl and not NOT_DECL.match(raw) and decl.group(1) not in KW else None
        if in_block:
            end = raw.find("*/")
            if end < 0:
                out.append(_comment(raw, doc))
                continue
            res.append(_comment(raw[: end + 2], doc))
            i, in_block = end + 2, False
        plain = re.match(r"\s*(import|package)\b", raw)  # IntelliJ leaves import paths uncoloured
        if plain and not in_block:
            res.append(f'{esc(raw[:plain.start(1)])}<span class="k">{plain.group(1)}</span>{esc(raw[plain.end(1):])}')
            out.append("".join(res))
            continue
        while i < len(raw):
            m = token.search(raw, i)
            if not m:
                res.append(esc(raw[i:]))
                break
            res.append(esc(raw[i : m.start()]))
            kind, text = m.lastgroup, m.group()
            if kind == "bstart":
                doc = raw.startswith("/**", m.start())
                end = raw.find("*/", m.end())
                if end < 0:
                    res.append(_comment(raw[m.start():], doc))
                    in_block = True
                    break
                res.append(_comment(raw[m.start():end + 2], doc))
                i = end + 2
                continue
            cls = {"str": "s", "chr": "s", "com": "c", "ann": "a", "num": "n"}.get(kind)
            if kind == "word":
                before = raw[: m.start()].rstrip()
                after = raw[m.end():].lstrip()
                if text in KW:
                    cls = "k"
                elif text == decl_name and after.startswith("("):
                    cls, decl_name = "m", None
                elif after.startswith("(") and (
                    (before.endswith(".") and re.search(r"\b[A-Z]\w*\.$", before))
                    or (text in statics and not before.endswith("."))
                ):
                    cls = "i"  # static call: Foo.bar( or an own static method
                elif len(text) > 1 and text.isupper() and re.search(r"[A-Z]", text):
                    cls = "f i"  # constant
                elif text in fields and not after.startswith("("):
                    cls = "f"
                elif text[0].isupper():
                    cls = "t"
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
    global KW
    ext = path.suffix.lower()
    KW = C_KW | KW_BY_EXT.get(ext, set())
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
    """-> (status, added_line_set, {line_after_which_old_lines_go: [old line, ...]})

    Every hunk that removed or replaced lines keeps the old text, anchored to the last new line of
    the hunk (or the line before a pure deletion), so the page can show what was there before.
    """
    top = toplevel(path)
    if not top:
        return "unchanged", set(), {}
    rel = str(path.relative_to(top))
    st = git(top, "status", "--porcelain", "--", rel)
    if st.startswith("??"):
        return "new", set(range(1, 10**7)), {}
    out = git(top, "diff", "-U0", "--no-color", base, "--", rel)
    if not out:
        return "unchanged", set(), {}
    if "\nnew file mode" in out or out.startswith("new file mode"):
        return "new", set(range(1, 10**7)), {}
    added, old = set(), {}
    at = None
    for line in out.split("\n"):
        m = re.match(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            start, new_n = int(m.group(2)), int(m.group(3) or 1)
            if new_n:
                added.update(range(start, start + new_n))
            at = max(1, start + new_n - 1 if new_n else start)
        elif at is not None and line.startswith("-") and not line.startswith("---"):
            old.setdefault(at, []).append(line[1:])
    return "modified", added, old


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
        "old_lines": {k: highlight(path, v) for k, v in deleted.items()},
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
        mark = ""
        if i in p["deleted"]:
            cls.append("del")
            n_old = len(p["deleted"][i])
            mark = (
                f'<button class="dm" type="button" aria-label="{n_old} {esc(L["deleted_lines"])}"'
                f' data-count="{n_old} {esc(L["deleted_lines"])}"></button>'
            )
        if any(p["notes"][k]["step"] is not None for k in starts.get(i, [])):
            attrs += f' id="{anchor_id}-L{i}"'
        rows.append(
            f'<div class="{" ".join(cls)}" data-n="{i}"{attrs}><span class="no">{mark}{i}</span>'
            f'<span class="tx">{code or " "}</span></div>'
        )
        if i in p["deleted"]:
            olds = "".join(
                f'<div class="dl"><span class="no">−</span><span class="tx">{c or " "}</span></div>'
                for c in p["old_lines"][i]
            )
            rows.append(f'<div class="dels"><div class="dels-h">{esc(L["old_version"])}</div>{olds}</div>')
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
            f'<div class="seq-wrap" id="{f["id"]}-seq">{seq_svg(f["actors"], f["msgs"])}</div>'
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
    parts.append(rail_html(f, code, models, L))
    hidden = "" if first else " hidden"
    return (
        f'<div class="flow" id="flow-{f["id"]}" role="tabpanel" aria-labelledby="tab-{f["id"]}" '
        f'style="--flow:{color}"{hidden}>{"".join(parts)}</div>'
    )


def rail_html(f, code, models, L):
    """Execution-order navigator: one entry per step, linked to every code line carrying it."""
    targets = {}
    panels = [(p, f'{f["id"]}-f{i + 1}') for i, p in enumerate(code)]
    panels += [(p, f'{f["id"]}-m{i + 1}') for i, p in enumerate(models)]
    for p, pid in panels:
        for n in p["notes"]:
            if n["step"] is not None:
                targets.setdefault(str(n["step"]), []).append((f'{pid}-L{n["line"]}', p["name"], n["line"], n["text"]))
    actors = {a[0]: a[1] for a in f.get("actors", [])}
    steps = []
    for m in f.get("msgs", []):
        if len(m) > 4 and m[4] is not None and str(m[4]) not in [x[0] for x in steps]:
            who = actors.get(m[0], m[0]) if m[0] == m[1] else f"{actors.get(m[0], m[0])} → {actors.get(m[1], m[1])}"
            steps.append((str(m[4]), m[2], who))
    for key, ts in targets.items():
        if key not in [x[0] for x in steps]:
            text = ts[0][3]
            steps.append((key, text if len(text) <= 60 else text[:57] + "…", ts[0][1]))
    if not steps:
        return ""

    def order(x):
        return (0, float(x[0])) if x[0].replace(".", "", 1).isdigit() else (1, 0)

    items = []
    for key, label, who in sorted(steps, key=order):
        ts = targets.get(key, [])
        first = ts[0][0] if ts else f'{f["id"]}-seq'
        subs = ""
        if len(ts) > 1:
            subs = "<ul>" + "".join(
                f'<li><button type="button" data-target="{t}">{esc(name)}<span>:{line}</span></button></li>'
                for t, name, line, _ in ts
            ) + "</ul>"
        where = f'{esc(ts[0][1])}:{ts[0][2]}' if len(ts) == 1 else ("" if ts else esc(L["rail_diagram"]))
        where_html = f'<span class="rs-w">{where}</span>' if where else ""
        nocode = "" if ts else " nocode"
        items.append(
            f'<li class="rs{nocode}" data-step="{esc(key)}"><button type="button" class="rs-b" data-target="{first}">'
            f'<span class="step">{esc(key)}</span><span class="rs-t"><span class="rs-l">{esc(label)}</span>'
            f'<span class="rs-a">{esc(who)}</span>{where_html}</span></button>{subs}</li>'
        )
    return (
        f'<aside class="rail" aria-label="{esc(L["rail_title"])}"><div class="rail-h"><b>{esc(L["rail_title"])}</b>'
        f'<span class="rail-nav"><button type="button" data-dir="-1" aria-label="prev">‹</button>'
        f'<button type="button" data-dir="1" aria-label="next">›</button></span></div>'
        f'<p class="rail-hint">{esc(L["rail_hint"])}</p><ol>{"".join(items)}</ol></aside>'
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
  <button type="button" class="rail-toggle" aria-expanded="false">{esc(L["rail_toggle"])}</button>
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
