# code-walkthrough

A Claude Code skill that explains a change the way a colleague would at a whiteboard — one tab per
entry point, what goes in and what comes out, a numbered call diagram, then every class in the order
it runs with notes drawn out of the code by arrows. Published as a private Artifact link.

It was built for reading a branch you did not write: a feature that spans a controller, three
services, a cache, a REST client and a migration, where the diff alone tells you *what* changed but
not *how a request moves through it*.

## Install

```
/plugin marketplace add tahaakocer/code-walkthrough
/plugin install code-walkthrough@tahaakocer-plugins
```

Then, in any repository:

```
/code-walkthrough
```

Asking in plain words works too — "walk me through this diff", "explain the changes with arrows".
The page is written in the language you talk to Claude in.

## What the page gives you

| | |
|---|---|
| **One tab per flow** | Each endpoint or entry point gets its own tab, plus one for migrations, config and the rest |
| **Request → response** | An example request, the normal answer, and the alternative outcomes (skipped, 422, 503 …) |
| **Call diagram** | A numbered sequence diagram; the numbers match the notes on the code below |
| **Full code, in call order** | Every class the flow touches, complete, with notes tied to their lines by arrows |
| **Model classes** | The request, response and entity classes the flow carries — also from a sibling repo or library |
| **Diff markers** | Lines added or changed in the diff carry a green bar; a small red triangle in the gutter marks where lines were deleted |
| **Phone width** | Below 1000px the arrows give way to notes placed under their line |
| **Themes** | Light and dark, following the viewer's setting |

## Why a script and a spec

Claude never writes the page and never copies code. It writes a compact JSON spec — which files, in
which order, and a note per anchor (`"public Order create("` → "why this line matters"). The script
reads the code from disk, asks git which lines changed, draws the diagrams and writes the page.

Measured on a real feature branch — 29 files across a service and its model library, 35 code
panels, 123 notes, non-test diff ~300 KB:

| | characters | ~tokens | reaches the model |
|---|---|---|---|
| `SKILL.md`, loaded on every call | 5,963 | ~1,650 | **yes** |
| `inventory.py` map of the diff | 18,531 | ~5,150 | **yes** |
| The spec Claude writes (mostly the notes) | 33,657 | ~9,350 | **yes** |
| Raw non-test diff | 303,876 | ~84,400 | no |
| The generated page | 605,370 | ~168,200 | no |

A first run spends roughly **16,000 tokens** plus whatever reading Claude needs to understand the
change — against ~168,000 for having the model write the page itself. Token figures are estimates
(characters ÷ 3.6).

Later runs on the same branch are cheaper: the spec is stored in
`~/.cache/code-walkthrough/<repo>/<branch>/spec.json`, anchors are text fragments that survive line
shifts, and `build.py` names the source files that changed since the last build, so only their notes
need another look.

## Try it without Claude

The repository ships the skill explaining itself:

```bash
python3 skills/code-walkthrough/scripts/build.py examples/self-walkthrough.json -o /tmp/walkthrough.html
```

And a map of any diff:

```bash
python3 skills/code-walkthrough/scripts/inventory.py              # working tree against HEAD
python3 skills/code-walkthrough/scripts/inventory.py --base main  # the branch against main
python3 skills/code-walkthrough/scripts/inventory.py --outline path/to/File.java
```

Python 3.8+ and git, no third-party packages. The page uses Google Fonts and the Artifact viewer's
built-in Mermaid for the optional overview and ER diagrams.

## The spec

The full schema is in [`SKILL.md`](skills/code-walkthrough/SKILL.md). The short version:

```json
{
  "lang": "en",
  "repo": "/abs/path/repo",
  "roots": {"model": "/abs/path/model-lib"},
  "flows": [{
    "id": "create", "tab": "Create order", "method": "POST", "url": "/api/v1/orders",
    "request": "…", "response": "…",
    "actors": [["ctl", "OrderController", "POST /orders"], ["svc", "OrderServiceImpl", "create()"]],
    "msgs": [["ctl", "svc", "create(request)", "call", 1]],
    "panels": [{"path": "src/main/…/OrderController.java", "role": "HTTP entry",
                "notes": [["public Order create(", "Validates and hands over to the service", 1]]}],
    "models": [{"root": "model", "path": "src/main/…/OrderRequest.java", "notes": []}]
  }]
}
```

Highlighting covers Java, Kotlin, JavaScript/TypeScript, Python, YAML/properties and HTML/XML well
enough to read; anything else still renders, just plainer.

## Customising the look

Everything visual lives in `skills/code-walkthrough/assets/`: `page.css` (light and dark tokens,
layout) and `page.js` (arrow drawing, tabs). Edit them and rebuild; every future page picks up the
change.

## Notes

- Untracked files count as entirely new; committed branch changes need `--base`.
- Published Artifacts are private to your account until you share them from the page's Share menu.
- The page shows your code in full. Mind what you share.

## Licence

MIT — see [LICENSE](LICENSE). Built by [@tahaakocer](https://github.com/tahaakocer).
