"""Web interface for the plagiarism checker.

Run:  python3 server.py   then open http://127.0.0.1:8000
"""

import argparse
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from plagiarism_checker import DEFAULT_DB, DEFAULT_THRESHOLD, PlagiarismChecker
from web_search import load_env_file

INDEX = Path(__file__).with_name("index.html")
MAX_BODY = 5_000_000


def _report(report):
    return {"found": report.found, "matches": [asdict(m) for m in report.matches]}


class Handler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB

    def _send(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/sources":
            checker = PlagiarismChecker(self.db_path)
            try:
                docs = checker.list_documents()
            finally:
                checker.close()
            self._send(200, [{"id": i, "title": t, "url": u} for i, t, u in docs])
        else:
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        try:
            body = self._json_body()
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        checker = PlagiarismChecker(self.db_path)
        try:
            if self.path == "/api/check":
                self._check(checker, body)
            elif self.path == "/api/sources":
                title, url, content = (str(body.get(k, "")).strip() for k in ("title", "url", "content"))
                if not (title and url and content):
                    return self._send(400, {"error": "Title, link and text are all required."})
                checker.add_document(title, url, content)
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "Not found"})
        finally:
            checker.close()

    def _check(self, checker, body):
        text = str(body.get("text", ""))
        if not text.strip():
            return self._send(400, {"error": "Enter some text to check."})
        threshold = float(body.get("threshold", DEFAULT_THRESHOLD))
        result = {"database": _report(checker.check(text, threshold))}
        if body.get("web"):
            from web_search import SearchError, check_web, make_search
            on_page = checker.add_document if body.get("save") else None
            keys = body.get("keys") or {}
            try:
                search = make_search(
                    keys.get("google_api_key") or None,
                    keys.get("google_cse_id") or None,
                    keys.get("brave_api_key") or None,
                )
                result["web"] = _report(check_web(text, threshold, search=search, on_page=on_page))
            except SearchError as e:
                result["web"] = {"error": str(e)}
            except Exception as e:
                result["web"] = {"error": f"Web search failed: {e}"}
        self._send(200, result)


def main():
    parser = argparse.ArgumentParser(description="Plagiarism checker web interface.")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    Handler.db_path = args.db
    load_env_file()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Plagiarism checker running at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
