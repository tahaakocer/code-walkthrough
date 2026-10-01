---
name: code-walkthrough
description: "Explains a diff (or a chosen code path) as a visual Artifact page, flow by flow: the request and response, a numbered call diagram, every class in the order it runs with explanation notes tied to their lines by arrows, and the model classes the flow carries. Use when the user asks to explain a diff or branch visually — 'walk me through this diff', 'explain the changes with arrows', 'diff'i görsel anlat', 'kodu oklarla açıkla' — or invokes /code-walkthrough. A script reads the code from disk; you write only anchors and notes."
---

# Code walkthrough

A script builds the page: code is read from disk, diff markers come from git. You write a compact
**spec JSON** of anchors and explanations. Never copy code into the spec or into your reply.

The scripts sit next to this file. Derive their path from here rather than assuming a home directory:
`${CLAUDE_PLUGIN_ROOT}/skills/code-walkthrough/scripts/` as a plugin,
`~/.claude/skills/code-walkthrough/scripts/` as a personal skill.

- `inventory.py [--base REF] [--tests]` — changed files, +/− counts, changed line ranges and a
  line-numbered outline (types, methods, endpoints). Tests are skipped by default.
- `inventory.py --outline FILE...` — outline of any file, e.g. model classes in another repo.
- `build.py SPEC.json -o OUT.html` — renders the page. Lists every broken anchor at once (exit 1) and
  names the source files that changed since the previous build.

## Language

Write every note, heading and summary **in the language the user speaks to you**, and set `"lang"`
to its code. UI labels are built in for `tr` and `en`; for any other language pass `"labels"` with
all of: `request response behind behind_hint read_code models models_hint new modified unchanged
deleted_lines legend before after old_version rail_title rail_hint rail_toggle rail_diagram back go_choose`.

## Saving tokens — hard rules

1. Look for a stored spec first: `~/.cache/code-walkthrough/<repo>/<branch>/spec.json` (`/` in the
   branch becomes `-`). If it exists, Edit it instead of rewriting; revisit only the notes of the
   files `build.py` reports as changed.
2. Understand the change from `inventory.py` plus `git diff -U3 -- <file>` for the files you need.
   Do not read whole files; read a method body with `sed -n 'A,Bp'` when you need it.
3. Anchor notes with a short, unique **text fragment** of the line (`"public Foo create("`) — it
   survives line shifts. A repeated fragment takes `["fragment", 2]` (second match). A line number
   (int) works too but breaks when the code moves.
4. Write the spec with a single Write. When the build fails, Edit only the broken anchors.
5. At most one screenshot to check (headless Chrome, if present). No loops.

## Steps

1. Run `inventory.py` at the repo root. Base `HEAD` (uncommitted work) unless the user means a branch
   comparison, then `--base main`.
2. Split the change into **flows as the caller sees them** — usually one endpoint or entry point per
   tab (`flows[]`). Changes that belong to no flow (migrations, config, bundles) go into a tab of
   `blocks`.
3. For each flow, list the files **in call order** as `panels[]`; put the request/response/entity
   classes it carries in `models[]` (in another repo or module → `roots` + `"root"`; find that path
   in the project's CLAUDE.md or its dependencies).
4. Match the sequence-diagram step numbers (`msgs[][4]`) with the `step` of the code notes.
5. Write the spec into the store, build, publish as an Artifact. The Artifact tool's rules apply
   (a new page starts with `quickstart`, intent `other`); the design is already in the template, so
   do no design work of your own. To update, publish the same `file_path` or the earlier `url`.
6. Reply briefly: the link, the tabs, and any risk worth flagging (e.g. a migration that deletes data).

## Spec

```json
{
  "lang": "en",
  "repo": "/abs/path/repo",
  "roots": {"model": "/abs/path/model-lib"},
  "base": "HEAD",
  "pageTitle": "Two-to-four-word name", "eyebrow": "repo · branch",
  "title": "Page heading", "subtitle": "One or two sentences",
  "before": "How it worked", "after": "How it works now",
  "overview": "flowchart LR\n  A --> B",
  "flows": [{
    "id": "create", "tab": "Create order", "method": "POST", "url": "/api/v1/orders",
    "color": 0,
    "who": "Who calls it · permission", "lead": "Two or three sentences on the flow",
    "request": "example request text", "response": "example response text",
    "alts": [["422", "when"], ["Inactive", "what happens"]],
    "actors": [["ctl", "OrderController", "subtitle"], ["svc", "OrderServiceImpl", "create()"]],
    "msgs": [["ctl", "svc", "create(request)", "call", 1], ["svc", "ctl", "result", "ret", 2]],
    "panels": [{"path": "src/main/.../OrderController.java", "role": "One-sentence job",
                "notes": [["public Order create(", "Note with `code` and **bold**", 1, 3]]}],
    "models": [{"root": "model", "path": "src/main/.../OrderRequest.java", "label": "model-lib / OrderRequest.java",
                "role": "Request body", "notes": [["private String sku;", "Required", 1]]}],
    "blocks": [{"h": "Heading"}, {"p": "Paragraph"}, {"warn": "Warning"}, {"mermaid": "erDiagram ..."},
               {"cards": [["Title", "Text"]]}]
  }]
}
```

Everything but `flows[].id`, `tab` and panel `path` is optional. `repo` defaults to the spec's
folder, `color` (0–5) to the tab order. `notes[i] = [anchor, text, step|null, span]`, where `span` is
how many lines to highlight (default 1). A self-call in `msgs` has `from == to`. Note text supports
only `` `code` `` and `**bold**`.

## Writing notes

- Say what the line does and why it matters; do not restate the code.
- Name error paths with their HTTP status and code (422 `UNKNOWN_TEMPLATE`).
- One to three short sentences per note. One note per meaningful decision or branch; none on imports
  or getters.
- Lead with what the diff added or changed; add short notes on unchanged lines the flow depends on.
