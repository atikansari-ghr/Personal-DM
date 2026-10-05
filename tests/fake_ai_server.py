"""A deterministic fake local AI server (OpenAI-compatible and Ollama APIs) for tests.

Runs on 127.0.0.1 in a thread, records every request body so tests can prove which document text was (not)
sent to the model, and answers with predictable content. Embeddings are hashed bag-of-words vectors so
semantic similarity behaves sensibly without a real model.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = 64


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"[a-zA-Z]{3,}", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeAI:
    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.analyze_reply = {"title": "Passport - Sample", "expiry_date": "2031-05-20", "issue_date": "2021-05-21",
                              "document_type": "Passport", "correspondent": "Ministry of Samples", "tags": ["travel"],
                              "summary": "A synthetic passport."}
        self.extra_citation = ""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def prompts(self) -> str:
        return "\n".join(json.dumps(body) for _p, body in self.requests)

    def _chat_text(self, messages) -> str:
        last = messages[-1]["content"]
        if isinstance(last, list):
            last = " ".join(part.get("text", "") for part in last if isinstance(part, dict))
        if "OCR TEXT" in last:
            return "Here you go:\n```json\n" + json.dumps(self.analyze_reply) + "\n```"
        if "single word OK" in last:
            return "OK"
        ids = re.findall(r"\[doc:([0-9a-f-]{36})\]", last)
        cite = f" [doc:{ids[0]}]" if ids else ""
        return f"I found it.{cite}{self.extra_citation}"

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.requests.append((self.path, {}))
                if self.path.endswith("/v1/models"):
                    return self._send(200, {"data": [{"id": "text-model"}, {"id": "embed-model"}, {"id": "vision-model"}]})
                if self.path.endswith("/api/tags"):
                    return self._send(200, {"models": [{"name": "llama3"}, {"name": "nomic-embed-text"}]})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                fake.requests.append((self.path, body))
                if self.path.endswith("/v1/chat/completions"):
                    return self._send(200, {"choices": [{"message": {"content": fake._chat_text(body["messages"])}}]})
                if self.path.endswith("/v1/embeddings"):
                    inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
                    return self._send(200, {"data": [{"index": i, "embedding": embed(t)} for i, t in enumerate(inputs)]})
                if self.path.endswith("/api/chat"):
                    return self._send(200, {"message": {"content": fake._chat_text(body["messages"])}})
                if self.path.endswith("/api/embed"):
                    return self._send(200, {"embeddings": [embed(t) for t in body["input"]]})
                self._send(404, {"error": "not found"})

        return H
