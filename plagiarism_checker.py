"""Simple plagiarism checker.

Keeps a SQLite database of source documents (title, link, text). When you
check a piece of text, it is compared against every document in the database
and the tool tells you whether the content is present and, if so, the link(s)
where it was found.

How matching works: text is normalised (lowercase, punctuation stripped) and
split into overlapping word n-grams ("shingles"). Each stored document's
shingles are indexed, so a check only has to look up the shingles of the
query. A document's score is the share of the query's shingles that also
appear in that document (0-100%).
"""

import argparse
import csv
import hashlib
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB = "sources.db"
SHINGLE_SIZE = 5
DEFAULT_THRESHOLD = 30.0  # percent of the query that must match to report

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text):
    return _WORD_RE.findall(text.lower())


def _hash(words):
    digest = hashlib.blake2b(" ".join(words).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def shingles(words, size=SHINGLE_SIZE):
    if len(words) < size:
        return set()
    return {_hash(words[i:i + size]) for i in range(len(words) - size + 1)}


@dataclass
class Match:
    title: str
    url: str
    score: float  # percent of the checked text found in this source


@dataclass
class Report:
    found: bool
    matches: list
    where: str = "in the database"

    def __str__(self):
        if not self.found:
            return f"NOT FOUND: this text was not found {self.where}."
        lines = [f"FOUND: this text is present {self.where}."]
        for m in self.matches:
            lines.append(f"  {m.score:5.1f}%  {m.title}\n          {m.url}")
        return "\n".join(lines)


class PlagiarismChecker:
    def __init__(self, db_path=DEFAULT_DB):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                normalized TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS shingles (
                hash INTEGER NOT NULL,
                doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                PRIMARY KEY (hash, doc_id)
            ) WITHOUT ROWID;
            """
        )
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self):
        self.conn.close()

    def add_document(self, title, url, content):
        """Add a source document, replacing any existing one with the same URL."""
        words = tokenize(content)
        with self.conn:
            self.conn.execute("DELETE FROM documents WHERE url = ?", (url,))
            cur = self.conn.execute(
                "INSERT INTO documents (title, url, content, normalized) VALUES (?, ?, ?, ?)",
                (title, url, content, " ".join(words)),
            )
            doc_id = cur.lastrowid
            self.conn.executemany(
                "INSERT OR IGNORE INTO shingles (hash, doc_id) VALUES (?, ?)",
                ((h, doc_id) for h in shingles(words)),
            )
        return doc_id

    def list_documents(self):
        return self.conn.execute("SELECT id, title, url FROM documents ORDER BY id").fetchall()

    def check(self, text, threshold=DEFAULT_THRESHOLD):
        """Check text against every document in the database."""
        words = tokenize(text)
        if not words:
            return Report(False, [])

        query = shingles(words)
        if query:
            scores = self._shingle_scores(query)
        else:
            # Too short for shingles: look for the exact phrase instead.
            scores = self._phrase_scores(" ".join(words))

        matches = []
        for doc_id, score in scores.items():
            if score >= threshold:
                title, url = self.conn.execute(
                    "SELECT title, url FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
                matches.append(Match(title, url, round(score, 1)))
        matches.sort(key=lambda m: m.score, reverse=True)
        return Report(bool(matches), matches)

    def _shingle_scores(self, query):
        hashes = list(query)
        counts = {}
        # Stay under SQLite's bound-parameter limit.
        for i in range(0, len(hashes), 900):
            chunk = hashes[i:i + 900]
            rows = self.conn.execute(
                f"SELECT doc_id, COUNT(*) FROM shingles WHERE hash IN ({','.join('?' * len(chunk))}) "
                "GROUP BY doc_id",
                chunk,
            )
            for doc_id, n in rows:
                counts[doc_id] = counts.get(doc_id, 0) + n
        return {doc_id: 100.0 * n / len(query) for doc_id, n in counts.items()}

    def _phrase_scores(self, phrase):
        rows = self.conn.execute(
            "SELECT id FROM documents WHERE ' ' || normalized || ' ' LIKE ?",
            (f"% {phrase} %",),
        )
        return {doc_id: 100.0 for (doc_id,) in rows}


def _read_text(args):
    if args.text is not None:
        return args.text
    if args.file is not None:
        return Path(args.file).read_text(encoding="utf-8")
    return sys.stdin.read()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Simple plagiarism checker.")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add a source document to the database")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--url", required=True, help="link to the source")
    src = p_add.add_mutually_exclusive_group()
    src.add_argument("--text")
    src.add_argument("--file", help="read content from this file (default: stdin)")

    p_import = sub.add_parser("import", help="bulk-import sources from a CSV with title,url,content columns")
    p_import.add_argument("csv_file")

    p_check = sub.add_parser("check", help="check whether text is present in the database")
    src = p_check.add_mutually_exclusive_group()
    src.add_argument("--text")
    src.add_argument("--file", help="read text from this file (default: stdin)")
    p_check.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"minimum %% of the text that must match to report a source (default: {DEFAULT_THRESHOLD})",
    )
    p_check.add_argument("--web", action="store_true", help="also search the web (needs a search API key)")
    p_check.add_argument("--save", action="store_true", help="with --web: save matching web pages into the database")

    sub.add_parser("list", help="list the sources in the database")

    args = parser.parse_args(argv)
    checker = PlagiarismChecker(args.db)
    try:
        if args.command == "add":
            checker.add_document(args.title, args.url, _read_text(args))
            print(f"Added: {args.title} ({args.url})")
        elif args.command == "import":
            with open(args.csv_file, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                checker.add_document(row["title"], row["url"], row["content"])
            print(f"Imported {len(rows)} document(s).")
        elif args.command == "check":
            text = _read_text(args)
            report = checker.check(text, args.threshold)
            print("Database:", report)
            found = report.found
            if args.web:
                from web_search import SearchError, check_web, load_env_file
                load_env_file()
                on_page = checker.add_document if args.save else None
                try:
                    web_report = check_web(text, args.threshold, on_page=on_page)
                except SearchError as e:
                    print(f"Web: error: {e}", file=sys.stderr)
                    return 2
                print("Web:", web_report)
                found = found or web_report.found
            return 1 if found else 0
        elif args.command == "list":
            docs = checker.list_documents()
            for doc_id, title, url in docs:
                print(f"{doc_id:4}  {title}  {url}")
            print(f"{len(docs)} document(s).")
    finally:
        checker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
