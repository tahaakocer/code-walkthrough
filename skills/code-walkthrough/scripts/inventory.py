#!/usr/bin/env python3
"""Compact map of a diff, so the walkthrough spec can be written without reading whole files.

    inventory.py [--base REF] [--tests] [--repo DIR]      changed files + outline + changed ranges
    inventory.py --outline FILE...                         outline of any files (e.g. model classes)

Per file it prints status, +/- counts, line count, the changed line ranges and an outline:
declarations, endpoint/transaction/listener annotations, with line numbers usable as anchors.
Test files are skipped unless --tests is given.
"""
import re
import subprocess
import sys
from pathlib import Path

TEST = re.compile(r"(^|/)(src/test|test|tests|__tests__|spec)/|(Test|Tests|IT)\.\w+$|\.(spec|test)\.\w+$")
DECL = re.compile(
    r"^\s*(?:@(?:Get|Post|Put|Patch|Delete|Request)Mapping|@(?:Transactional|EventListener|Bean|FeignClient|"
    r"KafkaListener|Scheduled|PreAuthorize|Entity|Table|Configuration|Service|Component|RestController)\b"
    r"|(?:public|protected|private|static|final|abstract|sealed|default|export|async|override|internal|open|data)?\s*"
    r"(?:class|interface|record|enum|object|fun|def|function|type)\s+\w+"
    r"|(?:public|protected|private|static|final|synchronized|default|\s)+[\w<>\[\], ?.]+\s+\w+\s*\([^;]*$"
    r"|(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s*)?\(|\s*<changeSet\b|\s*<createTable\b|\s*<dropColumn\b)"
)
SKIP = re.compile(r"^\s*(?:return|if|for|while|switch|catch|throw|new|else)\b")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout


def outline(path, ranges=None):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError as e:
        print(f"   ! {e}")
        return
    for i, line in enumerate(lines, 1):
        if DECL.match(line) and not SKIP.match(line):
            mark = "*" if ranges and any(a <= i <= b for a, b in ranges) else " "
            print(f"  {mark}{i:5}  {line.strip()[:110]}")


def changed_ranges(repo, base, rel):
    out = git(repo, "diff", "-U0", base, "--", rel)
    ranges = []
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", out, re.M):
        start, n = int(m.group(1)), int(m.group(2) or 1)
        ranges.append((start, start + max(n, 1) - 1) if n else (start, start))
    return ranges


def main():
    args = sys.argv[1:]
    if "--outline" in args:
        for f in args[args.index("--outline") + 1 :]:
            n = len(Path(f).read_text(errors="replace").split("\n")) if Path(f).is_file() else 0
            print(f"{f}  ({n} lines)")
            outline(f)
        return
    base = args[args.index("--base") + 1] if "--base" in args else "HEAD"
    repo = args[args.index("--repo") + 1] if "--repo" in args else "."
    tests = "--tests" in args
    top = git(repo, "rev-parse", "--show-toplevel").strip()
    if not top:
        sys.exit("not a git repository")
    numstat = {}
    for line in git(top, "diff", "--numstat", base).splitlines():
        a, d, p = line.split("\t", 2)
        numstat[p] = (a, d)
    entries = []
    for line in git(top, "status", "--porcelain", "-uall").splitlines():
        code, p = line[:2], line[3:].split(" -> ")[-1]
        entries.append(("??" if code == "??" else code.strip() or "M", p))
    for p in numstat:
        if not any(e[1] == p for e in entries):
            entries.append(("C", p))  # committed on the branch since base
    skipped = 0
    print(f"repo {top}  base {base}   (* = line inside a changed range)")
    for code, p in sorted(entries, key=lambda e: e[1]):
        if not tests and TEST.search(p):
            skipped += 1
            continue
        full = Path(top) / p
        a, d = numstat.get(p, ("?", "?"))
        if code == "D" or not full.exists():
            print(f"\nD  {p}  (deleted)")
            continue
        n = len(full.read_text(errors="replace").split("\n"))
        ranges = None if code == "??" else changed_ranges(top, base, p)
        rtxt = "all" if ranges is None else ", ".join(f"{x}-{y}" if x != y else str(x) for x, y in ranges[:12])
        stat = "new" if code == "??" else f"+{a} -{d}"
        print(f"\n{code:2} {p}  ({stat}, {n} lines; changed: {rtxt})")
        if full.suffix.lower() in {".properties", ".json", ".md", ".lock"}:
            continue
        outline(full, ranges)
    if skipped:
        print(f"\n({skipped} test files skipped; pass --tests to include)")


if __name__ == "__main__":
    main()
