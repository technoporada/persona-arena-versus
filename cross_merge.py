#!/usr/bin/env python3
"""
cross_merge.py — Cross-source merge: laczy projekty z 3 zrodel w jedna strukture.

Dziala na juz zmergeowanych folderach:
  /home/h5n1/Pobrane/deepseek_merged/
  /home/h5n1/Pobrane/claude_merged/
  /home/h5n1/Pobrane/gemini_merged/

Output:
  /home/h5n1/Pobrane/cross_merged/
    <project_name>/
      gemini__<file>
      claude__<file>
      deepseek__<file>
      _README.md          <- statystyki projektu
  /home/h5n1/Pobrane/cross_merged/_INDEX.db  (SQLite z FTS5)
  /home/h5n1/Pobrane/cross_merged/_SUMMARY.md

Usage:
  python cross_merge.py \\
      --deepseek /home/h5n1/Pobrane/deepseek_merged \\
      --claude /home/h5n1/Pobrane/claude_merged \\
      --gemini /home/h5n1/Pobrane/gemini_merged \\
      --out /home/h5n1/Pobrane/cross_merged
"""

import os
import hashlib
import sqlite3
import argparse
import datetime
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Tuple

# -----------------------
# Config
# -----------------------

# Projekty do ignorowania (smietnik)
IGNORE_PROJECTS = {"Fragments_Misc", "Fragments", "Misc", "TODO"}

# Plik ignorowane
IGNORE_FILES = {"_VALIDATION_REPORT.md", "README.md", ".DS_Store", "Thumbs.db"}

# -----------------------
# Language detection
# -----------------------

EXT_TO_LANG = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".ps1": "powershell", ".psm1": "powershell",
    ".html": "html", ".htm": "html",
    ".css": "css",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".cs": "csharp",
    ".rs": "rust",
    ".go": "go",
    ".sql": "sql",
    ".json": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".dockerfile": "docker",
    ".php": "php",
    ".rb": "ruby",
    ".java": "java",
}


def detect_lang(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if not ext and filename.lower() == "dockerfile":
        return "docker"
    return EXT_TO_LANG.get(ext, "unknown")


def is_code_file(filename: str) -> bool:
    return detect_lang(filename) != "unknown" and detect_lang(filename) != "markdown"


# -----------------------
# Walk merged dirs
# -----------------------

def scan_source(source_dir: str, source_name: str) -> Dict[str, List[Dict]]:
    """
    Walks source_dir/<project>/<files>.
    Returns: {project_name: [{file, path, lang, lines, hash, content}]}
    """
    projects = defaultdict(list)
    if not os.path.isdir(source_dir):
        print(f"  [warn] {source_dir} not found")
        return projects

    for entry in sorted(os.listdir(source_dir)):
        entry_path = os.path.join(source_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        if entry in IGNORE_PROJECTS:
            continue
        # Walk recursively
        for root, dirs, files in os.walk(entry_path):
            for fn in files:
                if fn in IGNORE_FILES:
                    continue
                if not is_code_file(fn):
                    continue
                fpath = os.path.join(root, fn)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception:
                    continue
                h = hashlib.sha256(content.encode("utf-8")).hexdigest()
                projects[entry].append({
                    "file": fn,
                    "path": fpath,
                    "lang": detect_lang(fn),
                    "lines": content.count("\n") + 1,
                    "chars": len(content),
                    "hash": h,
                    "content": content,
                    "source": source_name,
                    "rel_path": os.path.relpath(fpath, entry_path)
                })
    return projects


# -----------------------
# Cross-merge
# -----------------------

def cross_merge(sources: Dict[str, Dict[str, List[Dict]]], out_dir: str) -> Tuple[int, int, int]:
    """
    sources: {source_name: {project: [files]}}
    Output: cross_merged/<project>/<source>__<file>
    """
    os.makedirs(out_dir, exist_ok=True)
    all_projects = set()
    for src_data in sources.values():
        all_projects.update(src_data.keys())

    total_files = 0
    total_dedup = 0
    total_projects = 0

    for project in sorted(all_projects):
        project_dir = os.path.join(out_dir, project)
        os.makedirs(project_dir, exist_ok=True)

        # Zbierz wszystkie pliki z wszystkich zrodel dla tego projektu
        seen_hashes = set()
        project_files = []
        for src_name, src_data in sources.items():
            for f in src_data.get(project, []):
                # Deduplikacja per-project
                if f["hash"] in seen_hashes:
                    total_dedup += 1
                    continue
                seen_hashes.add(f["hash"])
                project_files.append((src_name, f))

        if not project_files:
            continue

        total_projects += 1

        # Zapisz pliki z prefixem zrodla
        for src_name, f in project_files:
            # Zachowaj rozszerzenie, dodaj prefix zrodla
            out_name = f"{src_name}__{f['file']}"
            # Unikaj kolizji
            out_path = os.path.join(project_dir, out_name)
            counter = 1
            while os.path.exists(out_path):
                out_path = os.path.join(project_dir, f"{src_name}__{counter}_{f['file']}")
                counter += 1
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(f["content"])
            total_files += 1

        # README per project
        readme_path = os.path.join(project_dir, "_README.md")
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(f"# {project}\n\n")
            fh.write(f"Cross-source merge: {len(project_files)} unique files\n\n")
            by_source = defaultdict(int)
            by_lang = defaultdict(int)
            total_lines = 0
            for src_name, f in project_files:
                by_source[src_name] += 1
                by_lang[f["lang"]] += 1
                total_lines += f["lines"]
            fh.write("## By source\n\n| source | files |\n|---|---|\n")
            for src_name in ["gemini", "claude", "deepseek"]:
                if src_name in by_source:
                    fh.write(f"| {src_name} | {by_source[src_name]} |\n")
            fh.write("\n## By language\n\n| lang | files |\n|---|---|\n")
            for lang, count in sorted(by_lang.items(), key=lambda x: -x[1]):
                fh.write(f"| {lang} | {count} |\n")
            fh.write(f"\n## Total lines: {total_lines}\n")

    return total_projects, total_files, total_dedup


# -----------------------
# SQLite index
# -----------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    source TEXT NOT NULL,
    filename TEXT NOT NULL,
    language TEXT,
    line_count INTEGER,
    char_count INTEGER,
    hash TEXT,
    path TEXT,
    content TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    content,
    content='files',
    content_rowid='id'
);

CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


def build_index(sources: Dict[str, Dict[str, List[Dict]]], db_path: str):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    seen_hashes = set()
    inserted = 0
    for src_name, src_data in sources.items():
        for project, files in src_data.items():
            if project in IGNORE_PROJECTS:
                continue
            for f in files:
                if f["hash"] in seen_hashes:
                    continue
                seen_hashes.add(f["hash"])
                cur.execute(
                    "INSERT INTO files (project, source, filename, language, line_count, char_count, hash, path, content) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        project, src_name, f["file"], f["lang"],
                        f["lines"], f["chars"], f["hash"], f["path"], f["content"]
                    )
                )
                inserted += 1
    conn.commit()
    conn.close()
    return inserted


# -----------------------
# Summary report
# -----------------------

def write_summary(sources: Dict[str, Dict[str, List[Dict]]], out_dir: str, stats: Tuple[int, int, int]):
    total_projects, total_files, total_dedup = stats
    summary_path = os.path.join(out_dir, "_SUMMARY.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# Cross-Source Merge — Summary\n\n")
        f.write(f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n\n")
        f.write("## Totals\n\n")
        f.write(f"- Projects (cross-source): **{total_projects}**\n")
        f.write(f"- Unique files: **{total_files}**\n")
        f.write(f"- Duplicates removed: **{total_dedup}**\n\n")

        # Per-source
        f.write("## Per source\n\n| source | projects | files |\n|---|---|---|\n")
        for src_name in ["gemini", "claude", "deepseek"]:
            if src_name in sources:
                n_proj = len(sources[src_name])
                n_files = sum(len(v) for v in sources[src_name].values())
                f.write(f"| {src_name} | {n_proj} | {n_files} |\n")

        # Per-project cross-source matrix
        all_projects = set()
        for src_data in sources.values():
            all_projects.update(src_data.keys())
        all_projects.discard("Fragments_Misc")

        f.write("\n## Per-project file counts (after dedup)\n\n")
        f.write("| project | gemini | claude | deepseek | total |\n|---|---|---|---|---|\n")
        for project in sorted(all_projects):
            row = [project]
            total = 0
            for src_name in ["gemini", "claude", "deepseek"]:
                n = len(sources.get(src_name, {}).get(project, []))
                row.append(str(n) if n else "-")
                total += n
            if total > 0:
                row.append(str(total))
                f.write("| " + " | ".join(row) + " |\n")

        # Top languages
        lang_counts = defaultdict(int)
        lang_lines = defaultdict(int)
        for src_data in sources.values():
            for files in src_data.values():
                for fobj in files:
                    lang_counts[fobj["lang"]] += 1
                    lang_lines[fobj["lang"]] += fobj["lines"]
        f.write("\n## Top languages\n\n| lang | files | lines |\n|---|---|---|\n")
        for lang in sorted(lang_counts.keys(), key=lambda l: -lang_counts[l]):
            f.write(f"| {lang} | {lang_counts[lang]} | {lang_lines[lang]} |\n")

    print(f"\nSummary written: {summary_path}")


# -----------------------
# Main
# -----------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deepseek", required=True)
    parser.add_argument("--claude", required=True)
    parser.add_argument("--gemini", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    print("=== CROSS-MERGE START ===\n")

    # Scan all 3 sources
    sources = {}
    print("[1/4] Scanning Gemini...")
    sources["gemini"] = scan_source(args.gemini, "gemini")
    print(f"  -> {len(sources['gemini'])} projects")

    print("[2/4] Scanning Claude...")
    sources["claude"] = scan_source(args.claude, "claude")
    print(f"  -> {len(sources['claude'])} projects")

    print("[3/4] Scanning DeepSeek...")
    sources["deepseek"] = scan_source(args.deepseek, "deepseek")
    print(f"  -> {len(sources['deepseek'])} projects")

    # Cross-merge
    print("\n[4/4] Cross-merging...")
    stats = cross_merge(sources, args.out)
    print(f"  -> {stats[0]} projects, {stats[1]} unique files, {stats[2]} duplicates removed")

    # Build SQLite index
    db_path = os.path.join(args.out, "_INDEX.db")
    print(f"\nBuilding SQLite index: {db_path}")
    n = build_index(sources, db_path)
    print(f"  -> {n} files indexed (deduplicated)")

    # Summary
    write_summary(sources, args.out, stats)

    print("\n=== DONE ===")
    print(f"Output: {args.out}")
    print("\nNastepne kroki:")
    print(f"  cat {args.out}/_SUMMARY.md                      # przeglad")
    print(f"  sqlite3 {db_path} 'SELECT project, COUNT(*) FROM files GROUP BY project;'")
    print(f"  sqlite3 {db_path} \"SELECT project, filename FROM files_fts WHERE files_fts MATCH 'telegram';\"")


if __name__ == "__main__":
    main()
