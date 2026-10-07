# Plagiarism Checker

A simple plagiarism checker. It keeps a database of source documents (title, link, text).
When you check some text, it compares it against **every** document in the database and tells you:

- **FOUND**, plus the link(s) to the matching source(s) and how much of your text matched, or
- **NOT FOUND**, if the text isn't in the database.

It's pure Python (3.8+), with no dependencies. The database is a local SQLite file (`sources.db`).

## Quick start

```bash
# 1. Load some sources into the database (CSV with title,url,content columns)
python3 plagiarism_checker.py import sample_sources.csv

# 2. Check some text
python3 plagiarism_checker.py check --text "Python is a high-level, general-purpose programming language. Its design philosophy emphasizes code readability."
```

Output:

```
FOUND: this text is present in the database.
   78.6%  Python (programming language)
          https://en.wikipedia.org/wiki/Python_(programming_language)
```

## Web page

```bash
python3 server.py
```

Then open <http://127.0.0.1:8000> in your browser. Paste text and click **Check** to see whether it's
in the database (and, if you tick the box, on the web), with links to each match. You can also add
sources and see what's in the database. The page (`index.html`) needs `server.py` running; opening
the file on its own won't work. For web search, set your Google keys (see below) before starting the server.

## Commands

| Command | What it does |
|---|---|
| `add --title T --url U --file doc.txt` | Add one source (or `--text "..."`, or pipe via stdin). Re-adding the same URL replaces it. |
| `import sources.csv` | Bulk-add sources from a CSV with `title,url,content` columns. |
| `check --file essay.txt` | Check text (or `--text "..."`, or stdin). Exit code is `1` if found, `0` if not. |
| `check ... --threshold 50` | Only report sources matching at least 50% of the text (default 30). |
| `check ... --web` | Also search the web (Google or Brave). Shows matching page links. |
| `check ... --web --save` | Also save matching web pages into the database, so future checks find them offline. |
| `list` | List all sources in the database. |

Use `--db path/to/file.db` before the command to use a different database file.

## Checking against the web (Google)

`--web` takes the 3 longest sentences of your text, searches for each as an exact phrase,
downloads the top results and scores each page the same way as the database.

**Google setup (Programmable Search Engine + Custom Search JSON API):**

1. Create a search engine at <https://programmablesearchengine.google.com/> and copy its
   **Search engine ID** (the `cx` value).
2. In the [Google Cloud Console](https://console.cloud.google.com/), enable the
   **Custom Search API** and create an **API key** (APIs & Services → Credentials).
3. Set the keys and run:

```bash
export GOOGLE_API_KEY="your-api-key"
export GOOGLE_CSE_ID="your-search-engine-id"
python3 plagiarism_checker.py check --web --file essay.txt
```

Google gives 100 free queries a day; each check uses up to 3. Google has been limiting
whole-web search for new search engines, so check the current terms when you set it up.

**Alternative: Brave Search API.** Get a key at <https://brave.com/search/api/> and set
`BRAVE_API_KEY` instead. If both are set, Google is used.

Keep your keys out of git (don't put them in files you commit).

## How it works

Text is lowercased, punctuation is stripped, and it's split into overlapping 5-word sequences ("shingles").
Each source's shingles are indexed in the database, so a check only looks up the shingles of your text.
A source's score is the percentage of your text's shingles that also appear in it. Small edits such as
changed punctuation or capitalisation don't hide a match. Text shorter than 5 words is matched as an exact phrase.

## Use from Python

```python
from plagiarism_checker import PlagiarismChecker

checker = PlagiarismChecker("sources.db")
checker.add_document("My source", "https://example.com/page", "Some text ...")
report = checker.check("text to check")
print(report.found)
for m in report.matches:
    print(m.score, m.title, m.url)

from web_search import check_web
print(check_web("text to check"))  # needs GOOGLE_API_KEY + GOOGLE_CSE_ID
```

## Tests

```bash
python3 -m unittest
```
