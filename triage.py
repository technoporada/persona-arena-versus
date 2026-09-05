#!/usr/bin/env python3
"""
triage.py — Szybki przeglad cross_merged/ aby wybrac projekty do wskrzeszenia.

Usage (uruchom w cross_merged/):
  python triage.py                    # lista wszystkich projektow z metrykami
  python triage.py --project MailHunter    # szczegoly jednego projektu
  python triage.py --search "telegram"     # FTS search po zawartosci
  python triage.py --top 10                # top 10 projektow po liczbie linii
  python triage.py --lang python           # tylko Python pliki
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path


def find_db():
    """Znajdz _INDEX.db w aktualnym katalogu lub rodzicach."""
    for d in [os.getcwd()] + list(Path(os.getcwd()).parents):
        p = os.path.join(d, "_INDEX.db")
        if os.path.exists(p):
            return p
    return None


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_list(args):
    db = find_db()
    if not db:
        print("Nie znalazlem _INDEX.db. Uruchom w cross_merged/ lub rodzicu.")
        sys.exit(1)
    conn = get_conn(db)
    cur = conn.cursor()
    cur.execute("""
        SELECT project,
               COUNT(*) as files,
               SUM(line_count) as lines,
               COUNT(DISTINCT source) as sources
        FROM files
        GROUP BY project
        ORDER BY lines DESC
    """)
    rows = cur.fetchall()
    print(f"\n{'project':<35} {'files':>6} {'lines':>8} {'sources':>8}")
    print("-" * 65)
    for r in rows:
        print(f"{r['project'][:34]:<35} {r['files']:>6} {r['lines'] or 0:>8} {r['sources']:>8}")
    print(f"\nLacznie: {len(rows)} projektow")


def cmd_project(args):
    db = find_db()
    if not db:
        print("Nie znalazlem _INDEX.db.")
        sys.exit(1)
    conn = get_conn(db)
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE project = ? ORDER BY source, filename", (args.project,))
    rows = cur.fetchall()
    if not rows:
        print(f"Nie znaleziono projektu: {args.project}")
        sys.exit(1)
    print(f"\n=== {args.project} ({len(rows)} files) ===\n")
    total_lines = 0
    for r in rows:
        print(f"  [{r['source']}] {r['filename']} ({r['line_count']} lines, {r['language']})")
        total_lines += r['line_count'] or 0
    print(f"\nTotal: {total_lines} lines across {len(rows)} files")
    print("\nAby wyeksportowac konkretny plik:")
    print(f"  sqlite3 {db} \"SELECT content FROM files WHERE id=<N>;\" > file.py")


def cmd_search(args):
    db = find_db()
    if not db:
        print("Nie znalazlem _INDEX.db.")
        sys.exit(1)
    conn = get_conn(db)
    cur = conn.cursor()
    cur.execute("""
        SELECT f.project, f.source, f.filename, f.line_count, substr(f.content, 1, 150) as preview
        FROM files_fts ft
        JOIN files f ON f.id = ft.rowid
        WHERE files_fts MATCH ?
        ORDER BY f.line_count DESC
        LIMIT ?
    """, (args.query, args.limit))
    rows = cur.fetchall()
    if not rows:
        print(f"Brak trafien dla: {args.query}")
        return
    print(f"\n=== SEARCH: '{args.query}' ({len(rows)} results) ===\n")
    for r in rows:
        print(f"[{r['project']}/{r['source']}] {r['filename']} ({r['line_count']} lines)")
        print(f"  {r['preview'][:140]}...")
        print()


def cmd_top(args):
    db = find_db()
    if not db:
        print("Nie znalazlem _INDEX.db.")
        sys.exit(1)
    conn = get_conn(db)
    cur = conn.cursor()
    cur.execute("""
        SELECT project, COUNT(*) as files, SUM(line_count) as lines
        FROM files
        GROUP BY project
        ORDER BY lines DESC
        LIMIT ?
    """, (args.top,))
    rows = cur.fetchall()
    print(f"\n=== TOP {args.top} PROJEKTOW (po liniach) ===\n")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3}. {r['project']:<35} {r['files']:>4} files, {r['lines'] or 0:>6} lines")


def cmd_lang(args):
    db = find_db()
    if not db:
        print("Nie znalazlem _INDEX.db.")
        sys.exit(1)
    conn = get_conn(db)
    cur = conn.cursor()
    cur.execute("""
        SELECT project, COUNT(*) as files, SUM(line_count) as lines
        FROM files
        WHERE language = ?
        GROUP BY project
        ORDER BY lines DESC
        LIMIT 30
    """, (args.lang,))
    rows = cur.fetchall()
    print(f"\n=== PROJEKTY z jezykiem '{args.lang}' ===\n")
    for r in rows:
        print(f"  {r['project']:<35} {r['files']:>4} files, {r['lines'] or 0:>6} lines")


def main():
    parser = argparse.ArgumentParser(prog="triage")
    parser.add_argument("--project", help="Szczegoly projektu")
    parser.add_argument("--search", help="FTS search")
    parser.add_argument("--top", type=int, help="Top N projektow")
    parser.add_argument("--lang", help="Filtruj po jezyku")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if args.project:
        cmd_project(args)
    elif args.search:
        cmd_search(args)
    elif args.top:
        cmd_top(args)
    elif args.lang:
        cmd_lang(args)
    else:
        cmd_list(args)


if __name__ == "__main__":
    main()
