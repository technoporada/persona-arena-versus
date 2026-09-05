#!/usr/bin/env python3
"""
recover.py — Recovery pipeline dla kodu z rozmow AI.
Ekstraktuje bloki kodu z: Gemini Takeout JSON, Claude export, DeepSeek export.
Deduplikuje, indeksuje w SQLite z FTS5.

Usage:
  python recover.py scan --gemini-dir /path/to/takeout --claude-file /path/to/claude.json --deepseek-file /path/to/deepseek.json
  python recover.py stats
  python recover.py search "telegram bot"
  python recover.py export --hash <sha256> --out recovered.py
  python recover.py list --lang python --min-lines 50
"""

import os
import re
import sys
import json
import hashlib
import sqlite3
import argparse
import datetime
from typing import List, Dict, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recovery.db")

# -----------------------
# Database
# -----------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,           -- gemini|claude|deepseek
    conversation_id TEXT,
    message_id TEXT,
    language TEXT,                  -- python|javascript|bash|...
    content TEXT NOT NULL,
    line_count INTEGER,
    char_count INTEGER,
    extracted_at TEXT,
    raw_context TEXT                -- okolicznosci (kawałek tekstu przed blokiem)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    source TEXT,
    title TEXT,
    message_count INTEGER,
    first_seen TEXT,
    last_seen TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5(
    content,
    content='blocks',
    content_rowid='id'
);

CREATE TRIGGER blocks_ai AFTER INSERT ON blocks BEGIN
    INSERT INTO blocks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER blocks_ad AFTER DELETE ON blocks BEGIN
    INSERT INTO blocks_fts(blocks_fts, rowid, content) VALUES('delete', old.id, old.content);
END;
CREATE TRIGGER blocks_au AFTER UPDATE ON blocks BEGIN
    INSERT INTO blocks_fts(blocks_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO blocks_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# -----------------------
# Code block extraction
# -----------------------

# Markdown code fence: ```lang\n...\n```
FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)

# Language normalization
LANG_MAP = {
    "py": "python", "python3": "python", "py3": "python",
    "js": "javascript", "node": "javascript", "nodejs": "javascript",
    "ts": "typescript",
    "sh": "bash", "shell": "bash", "zsh": "bash", "bashrc": "bash",
    "ps1": "powershell", "ps": "powershell",
    "html5": "html", "htm": "html",
    "c++": "cpp", "cxx": "cpp",
    "c#": "csharp", "cs": "csharp",
    "rs": "rust",
    "go": "go",
    "sql": "sql",
    "json": "json",
    "yaml": "yaml", "yml": "yaml",
    "css": "css",
    "dockerfile": "docker",
    "": "unknown",
}


def normalize_lang(lang: str) -> str:
    lang = lang.lower().strip()
    return LANG_MAP.get(lang, lang or "unknown")


def extract_blocks(text: str) -> List[Tuple[str, str, str]]:
    """
    Returns list of (language, content, context_preview).
    context_preview = 80 chars before the fence (helps identify project).
    """
    blocks = []
    for m in FENCE_RE.finditer(text):
        lang_raw = m.group(1)
        content = m.group(2)
        # context: 80 chars before fence
        start = max(0, m.start() - 200)
        context = text[start:m.start()].strip()[-200:]
        lang = normalize_lang(lang_raw)
        # skip empty / trivial blocks
        if len(content.strip()) < 20:
            continue
        blocks.append((lang, content, context))
    return blocks


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# -----------------------
# Source parsers
# -----------------------

def parse_gemini_dir(gemini_dir: str) -> List[Dict]:
    """
    Gemini Takeout structure varies. Look for *.json files containing conversations.
    Returns list of {conversation_id, message_text, source}.
    """
    items = []
    if not gemini_dir or not os.path.isdir(gemini_dir):
        return items

    for root, dirs, files in os.walk(gemini_dir):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            fpath = os.path.join(root, fn)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Gemini Takeout: usually list of conversations
                # Each conversation has turns with text
                convs = data if isinstance(data, list) else [data]
                for ci, conv in enumerate(convs):
                    conv_id = conv.get("id") or conv.get("conversation_id") or f"{fn}_{ci}"
                    # Walk through messages/turns
                    turns = (
                        conv.get("turns") or
                        conv.get("messages") or
                        conv.get("messages", []) or
                        []
                    )
                    for ti, turn in enumerate(turns):
                        text = ""
                        if isinstance(turn, dict):
                            text = (
                                turn.get("text") or
                                turn.get("content") or
                                turn.get("prompt") or
                                ""
                            )
                            if not text and "user_input" in turn:
                                ui = turn["user_input"]
                                text = ui.get("text", "") if isinstance(ui, dict) else str(ui)
                            if not text and "model_output" in turn:
                                mo = turn["model_output"]
                                text = mo.get("text", "") if isinstance(mo, dict) else str(mo)
                        elif isinstance(turn, str):
                            text = turn
                        if text:
                            items.append({
                                "source": "gemini",
                                "conversation_id": str(conv_id),
                                "message_id": str(ti),
                                "text": text
                            })
            except Exception as e:
                print(f"  [warn] failed to parse {fpath}: {e}", file=sys.stderr)
    return items


def parse_claude_export(claude_file: str) -> List[Dict]:
    """Claude export: usually JSON with conversations array."""
    items = []
    if not claude_file or not os.path.exists(claude_file):
        return items
    try:
        with open(claude_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [warn] claude parse: {e}", file=sys.stderr)
        return items

    convs = []
    if isinstance(data, list):
        convs = data
    elif isinstance(data, dict):
        convs = data.get("conversations") or data.get("chats") or [data]

    for conv in convs:
        conv_id = conv.get("uuid") or conv.get("id") or conv.get("name", "")[:50]
        messages = conv.get("chat_messages") or conv.get("messages") or []
        for msg in messages:
            text = msg.get("text") or ""
            if not text and msg.get("content"):
                c = msg["content"]
                text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
            sender = msg.get("sender") or msg.get("role") or ""
            if text:
                items.append({
                    "source": "claude",
                    "conversation_id": str(conv_id),
                    "message_id": str(msg.get("uuid") or sender),
                    "text": text
                })
    return items


def parse_deepseek_export(deepseek_file: str) -> List[Dict]:
    """DeepSeek export: usually JSON."""
    items = []
    if not deepseek_file or not os.path.exists(deepseek_file):
        return items
    try:
        with open(deepseek_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [warn] deepseek parse: {e}", file=sys.stderr)
        return items

    convs = []
    if isinstance(data, list):
        convs = data
    elif isinstance(data, dict):
        convs = data.get("conversations") or data.get("chats") or [data]

    for conv in convs:
        conv_id = conv.get("id") or conv.get("conversation_id") or ""
        messages = conv.get("messages") or conv.get("chat_messages") or []
        for msg in messages:
            # DeepSeek format varies — try common keys
            text = ""
            for key in ("text", "content", "message"):
                v = msg.get(key)
                if v:
                    text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                    break
            if text:
                items.append({
                    "source": "deepseek",
                    "conversation_id": str(conv_id),
                    "message_id": str(msg.get("id") or msg.get("role", "")),
                    "text": text
                })
    return items


# -----------------------
# Insert
# -----------------------

def insert_message(conn: sqlite3.Connection, msg: Dict) -> int:
    """Extract code blocks from one message and insert. Returns count inserted."""
    blocks = extract_blocks(msg["text"])
    inserted = 0
    cur = conn.cursor()
    for lang, content, context in blocks:
        h = hash_content(content)
        try:
            cur.execute(
                "INSERT OR IGNORE INTO blocks (hash, source, conversation_id, message_id, language, content, line_count, char_count, extracted_at, raw_context) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    h, msg["source"], msg["conversation_id"], msg["message_id"],
                    lang, content, content.count("\n") + 1, len(content),
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    context
                )
            )
            if cur.rowcount > 0:
                inserted += 1
        except sqlite3.IntegrityError:
            pass  # dup
    # update conversations table
    cur.execute(
        "INSERT OR IGNORE INTO conversations (id, source, title, message_count, first_seen, last_seen) VALUES (?,?,?,?,?,?)",
        (
            msg["conversation_id"], msg["source"], "", 1,
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
    )
    if cur.rowcount == 0:
        cur.execute(
            "UPDATE conversations SET message_count = message_count + 1, last_seen = ? WHERE id = ? AND source = ?",
            (datetime.datetime.now(datetime.timezone.utc).isoformat(), msg["conversation_id"], msg["source"])
        )
    conn.commit()
    return inserted


# -----------------------
# Commands
# -----------------------

def cmd_scan(args):
    total_msgs = 0
    total_blocks = 0
    conn = get_db()

    sources = []
    if args.gemini_dir:
        sources.append(("gemini", parse_gemini_dir(args.gemini_dir)))
    if args.claude_file:
        sources.append(("claude", parse_claude_export(args.claude_file)))
    if args.deepseek_file:
        sources.append(("deepseek", parse_deepseek_export(args.deepseek_file)))

    for src_name, msgs in sources:
        print(f"\n[{src_name}] {len(msgs)} messages to scan...")
        for msg in msgs:
            n = insert_message(conn, msg)
            total_msgs += 1
            total_blocks += n
        print(f"  -> {total_blocks} blocks so far")

    print("\n=== SCAN COMPLETE ===")
    print(f"Messages processed: {total_msgs}")
    print(f"Unique code blocks inserted: {total_blocks}")
    print(f"DB: {DB_PATH}")


def cmd_stats(args):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM blocks")
    total = cur.fetchone()[0]
    cur.execute("SELECT source, COUNT(*) FROM blocks GROUP BY source")
    by_source = cur.fetchall()
    cur.execute("SELECT language, COUNT(*), SUM(line_count) FROM blocks GROUP BY language ORDER BY COUNT(*) DESC")
    by_lang = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM conversations")
    convs = cur.fetchone()[0]

    print("\n=== RECOVERY STATS ===")
    print(f"Total unique code blocks: {total}")
    print(f"Conversations: {convs}")
    print("\nBy source:")
    for row in by_source:
        print(f"  {row[0]:<12} {row[1]:>6}")
    print("\nBy language:")
    print(f"  {'lang':<14} {'blocks':>8} {'lines':>10}")
    for row in by_lang:
        print(f"  {row[0]:<14} {row[1]:>8} {row[2] or 0:>10}")


def cmd_search(args):
    conn = get_db()
    cur = conn.cursor()
    # FTS5 search
    cur.execute(
        "SELECT b.id, b.source, b.language, b.line_count, substr(b.content, 1, 200) as preview "
        "FROM blocks_fts f JOIN blocks b ON b.id = f.rowid "
        "WHERE blocks_fts MATCH ? "
        "ORDER BY b.line_count DESC LIMIT ?",
        (args.query, args.limit)
    )
    rows = cur.fetchall()
    if not rows:
        print(f"No matches for: {args.query}")
        return
    print(f"\n=== SEARCH: '{args.query}' ({len(rows)} results) ===\n")
    for r in rows:
        print(f"[{r['id']}] {r['source']}/{r['language']} ({r['line_count']} lines)")
        print(f"  {r['preview'][:150]}...")
        print()


def cmd_list(args):
    conn = get_db()
    cur = conn.cursor()
    q = "SELECT id, source, language, line_count, substr(content, 1, 100) as preview FROM blocks WHERE 1=1"
    params = []
    if args.lang:
        q += " AND language = ?"
        params.append(args.lang)
    if args.min_lines:
        q += " AND line_count >= ?"
        params.append(args.min_lines)
    if args.source:
        q += " AND source = ?"
        params.append(args.source)
    q += " ORDER BY line_count DESC LIMIT ?"
    params.append(args.limit)
    cur.execute(q, params)
    rows = cur.fetchall()
    print(f"\n=== LIST ({len(rows)} blocks) ===\n")
    for r in rows:
        print(f"[{r['id']}] {r['source']}/{r['language']} {r['line_count']} lines — {r['preview'][:80]}")


def cmd_export(args):
    conn = get_db()
    cur = conn.cursor()
    if args.hash:
        cur.execute("SELECT content, language FROM blocks WHERE hash = ?", (args.hash,))
    else:
        cur.execute("SELECT content, language FROM blocks WHERE id = ?", (args.id,))
    row = cur.fetchone()
    if not row:
        print("Not found")
        sys.exit(1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(row["content"])
        print(f"Exported to {args.out}")
    else:
        print(row["content"])


def main():
    parser = argparse.ArgumentParser(prog="recover")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan")
    s.add_argument("--gemini-dir")
    s.add_argument("--claude-file")
    s.add_argument("--deepseek-file")

    sub.add_parser("stats")

    q = sub.add_parser("search")
    q.add_argument("query")
    q.add_argument("--limit", type=int, default=20)

    l = sub.add_parser("list")
    l.add_argument("--lang")
    l.add_argument("--source", choices=["gemini", "claude", "deepseek"])
    l.add_argument("--min-lines", type=int)
    l.add_argument("--limit", type=int, default=50)

    e = sub.add_parser("export")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", type=int)
    g.add_argument("--hash")
    e.add_argument("--out")

    args = parser.parse_args()
    if args.cmd == "scan":
        cmd_scan(args)
    elif args.cmd == "stats":
        cmd_stats(args)
    elif args.cmd == "search":
        cmd_search(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "export":
        cmd_export(args)


if __name__ == "__main__":
    main()
