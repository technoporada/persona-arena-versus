#!/usr/bin/env python3
"""
quality_scan.py - Static quality scan for merged AI conversation exports.

Walks claude_merged/, deepseek_merged/, gemini_merged/ (or any subdirs you point
it at) and produces:

  quality_report.csv      - one row per .py file (path, lines, funcs, classes,
                            status, notes)
  quality_summary.txt     - aggregate stats (totals per source, per status)
  duplicates.csv          - function signatures seen in >1 file
  broken.txt              - list of files with SyntaxError (one per line)
  monoliths.txt           - files with >500 lines (candidates to split)
  snippets.txt            - files with <10 non-blank lines (candidates to merge)

Status values:
  OK            - parses cleanly, has real content
  BROKEN        - SyntaxError on ast.parse
  EMPTY         - <3 non-blank, non-comment lines
  MARKDOWN_LIKE - first non-blank line looks like markdown, not Python
  SNIPPET       - 3-9 non-blank lines (too small to be standalone)
  MONOLITH      - >500 lines (review for splitting)

Usage:
  python quality_scan.py [root_dir]

  root_dir defaults to current working directory.
  Scans all immediate subdirectories ending in `_merged` (and their children).

Requirements: Python 3.8+, stdlib only.
"""

import ast
import csv
import hashlib
import os
import sys
from collections import defaultdict
from pathlib import Path


# ---------- helpers ----------

def count_real_lines(source: str) -> int:
    """Non-blank, non-comment line count."""
    n = 0
    for line in source.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        n += 1
    return n


def looks_like_markdown(source: str) -> bool:
    """Heuristic: first non-blank line is a markdown header or bullet,
    AND the file has zero Python keywords in first 5 non-blank lines."""
    first_lines = []
    for line in source.splitlines():
        s = line.strip()
        if not s:
            continue
        first_lines.append(s)
        if len(first_lines) >= 5:
            break
    if not first_lines:
        return False
    first = first_lines[0]
    if not (first.startswith("#") and " " in first and not first.startswith("#!")):
        # not a markdown header pattern
        if not first.startswith(("-", "*", "+ ")):
            return False
    # check absence of python-y tokens
    py_tokens = ("def ", "class ", "import ", "from ", "if __name__", "return ",
                 "print(", "@", "=")
    body = "\n".join(first_lines)
    return not any(tok in body for tok in py_tokens)


def func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Stable signature: name + arg count + arg names (ignore annotations/defaults)."""
    args = node.args
    arg_names = [a.arg for a in args.args]
    if args.vararg:
        arg_names.append("*" + args.vararg.arg)
    if args.kwarg:
        arg_names.append("**" + args.kwarg.arg)
    return f"{node.name}({','.join(arg_names)})"


def hash_sig(sig: str) -> str:
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]


# ---------- core scan ----------

def scan_file(path: Path) -> dict:
    """Return a row dict for one file."""
    row = {
        "path": str(path),
        "source": path.parts[0] if path.parts else "",
        "lines": 0,
        "real_lines": 0,
        "funcs": 0,
        "classes": 0,
        "status": "OK",
        "notes": "",
    }
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        row["status"] = "BROKEN"
        row["notes"] = f"read_error: {type(e).__name__}: {e}"
        return row

    row["lines"] = source.count("\n") + (0 if source.endswith("\n") or not source else 1)
    row["real_lines"] = count_real_lines(source)

    if row["real_lines"] == 0:
        row["status"] = "EMPTY"
        return row

    # Try to parse FIRST so broken files get flagged even if very short.
    tree = None
    parse_err = None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        parse_err = e

    if parse_err is not None:
        row["status"] = "BROKEN"
        row["notes"] = f"line {parse_err.lineno}: {parse_err.msg}"
        return row

    if row["real_lines"] < 3:
        row["status"] = "EMPTY"
        return row

    if looks_like_markdown(source):
        row["status"] = "MARKDOWN_LIKE"
        return row

    funcs = 0
    classes = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs += 1
        elif isinstance(node, ast.ClassDef):
            classes += 1
    row["funcs"] = funcs
    row["classes"] = classes

    if row["lines"] > 500:
        row["status"] = "MONOLITH"
    elif row["real_lines"] < 10:
        row["status"] = "SNIPPET"
    return row


def find_merged_dirs(root: Path) -> list[Path]:
    """Find immediate subdirs ending in _merged, or root itself."""
    if root.name.endswith("_merged"):
        return [root]
    out = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and p.name.endswith("_merged"):
            out.append(p)
    return out


# ---------- main ----------

def main():
    root_arg = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    root = Path(root_arg).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        sys.exit(2)

    merged_dirs = find_merged_dirs(root)
    if not merged_dirs:
        print(f"ERROR: no *_merged dirs found under {root}", file=sys.stderr)
        sys.exit(2)

    print(f"Scanning {len(merged_dirs)} source dir(s):")
    for d in merged_dirs:
        print(f"  - {d}")

    rows = []
    sig_to_files = defaultdict(list)  # sig_hash -> [(path, signature)]

    for d in merged_dirs:
        source_name = d.name
        for path in d.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            row = scan_file(path)
            row["source"] = source_name
            rows.append(row)

            # collect signatures for duplicate detection
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        sig = func_signature(node)
                        sig_to_files[hash_sig(sig)].append((str(path), sig))
            except Exception:
                pass  # broken files already flagged

    # write CSV
    csv_path = root / "quality_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "path", "source", "lines", "real_lines", "funcs", "classes",
            "status", "notes"
        ])
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {csv_path}  ({len(rows)} files)")

    # duplicates
    dup_path = root / "duplicates.csv"
    dup_count = 0
    with dup_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["signature", "file_count", "files"])
        for h, entries in sig_to_files.items():
            if len(entries) > 1:
                # group by signature string
                by_sig = defaultdict(list)
                for p, s in entries:
                    by_sig[s].append(p)
                for sig, paths in by_sig.items():
                    if len(paths) > 1:
                        w.writerow([sig, len(paths), ";".join(paths)])
                        dup_count += 1
    print(f"Wrote {dup_path}  ({dup_count} duplicate signatures)")

    # broken list
    broken_path = root / "broken.txt"
    broken = [r for r in rows if r["status"] == "BROKEN"]
    with broken_path.open("w", encoding="utf-8") as f:
        for r in broken:
            f.write(f"{r['path']}\t{r['notes']}\n")
    print(f"Wrote {broken_path}  ({len(broken)} broken files)")

    # monoliths
    mono_path = root / "monoliths.txt"
    monos = sorted([r for r in rows if r["status"] == "MONOLITH"],
                   key=lambda r: -r["lines"])
    with mono_path.open("w", encoding="utf-8") as f:
        for r in monos:
            f.write(f"{r['lines']}\t{r['path']}\n")
    print(f"Wrote {mono_path}  ({len(monos)} monoliths)")

    # snippets
    snip_path = root / "snippets.txt"
    snips = [r for r in rows if r["status"] == "SNIPPET"]
    with snip_path.open("w", encoding="utf-8") as f:
        for r in snips:
            f.write(f"{r['real_lines']}\t{r['path']}\n")
    print(f"Wrote {snip_path}  ({len(snips)} snippets)")

    # summary
    sum_path = root / "quality_summary.txt"
    by_status = defaultdict(int)
    by_source = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_status[r["status"]] += 1
        by_source[r["source"]][r["status"]] += 1

    with sum_path.open("w", encoding="utf-8") as f:
        f.write("QUALITY SCAN SUMMARY\n")
        f.write(f"Root: {root}\n")
        f.write(f"Total .py files: {len(rows)}\n\n")
        f.write("By status:\n")
        for s in ["OK", "BROKEN", "EMPTY", "MARKDOWN_LIKE", "SNIPPET", "MONOLITH"]:
            f.write(f"  {s:15s} {by_status.get(s, 0):6d}\n")
        f.write("\nBy source:\n")
        for src, counts in sorted(by_source.items()):
            total = sum(counts.values())
            f.write(f"  {src} (total {total}):\n")
            for s in ["OK", "BROKEN", "EMPTY", "MARKDOWN_LIKE", "SNIPPET", "MONOLITH"]:
                if counts.get(s, 0):
                    f.write(f"    {s:15s} {counts[s]:6d}\n")
        f.write(f"\nDuplicate function signatures: {dup_count}\n")
        f.write(f"Broken files (need fix or delete): {len(broken)}\n")
        f.write(f"Monoliths (consider splitting): {len(monos)}\n")
        f.write(f"Snippets (consider merging): {len(snips)}\n")
    print(f"Wrote {sum_path}")
    print("\nDone. Start with broken.txt and quality_summary.txt.")


if __name__ == "__main__":
    main()
