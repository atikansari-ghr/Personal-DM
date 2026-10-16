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
        # Change Set Y switches
        self.lmstudio = False        # reject response_format json_object exactly like LM Studio; list model types
        self.reject_schema = False   # reject any response_format (an older server without structured outputs)
        self.think = False           # wrap answers in a <think> block (Qwen3-style reasoning models)
        self.raw_reply = None        # a fixed (e.g. malformed) answer for document analysis
        self.echo_400 = False        # answer chat with 400 whose message echoes part of the prompt and a token
        self.fail_queue: list[int] = []  # statuses to answer the next chat requests with (503, 429, 400 ...)
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

    def chats(self) -> list[dict]:
        return [b for p, b in self.requests if p.endswith("/chat/completions") or p.endswith("/api/chat")]

    def analysis_chats(self) -> list[dict]:
        return [b for b in self.chats() if "OCR TEXT" in json.dumps(b)]

    def _chat_text(self, messages) -> str:
        last = messages[-1]["content"]
        if isinstance(last, list):
            last = " ".join(part.get("text", "") for part in last if isinstance(part, dict))
        if "OCR TEXT" in last:
            if self.raw_reply is not None:
                return self.raw_reply
            body = json.dumps(self.analyze_reply)
            return f"<think>Let me read the {{document}} first.</think>\n{body}" if self.think else "Here you go:\n```json\n" + body + "\n```"
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
                if self.path.endswith("/api/v0/models") and fake.lmstudio:
                    return self._send(200, {"data": [{"id": "text-model", "type": "llm"}, {"id": "embed-model", "type": "embeddings"},
                                                     {"id": "vision-model", "type": "vlm"}]})
                if self.path.endswith("/api/tags"):
                    return self._send(200, {"models": [{"name": "llama3"}, {"name": "nomic-embed-text"}]})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                fake.requests.append((self.path, body))
                if self.path.endswith("/v1/chat/completions"):
                    if fake.fail_queue:
                        code = fake.fail_queue.pop(0)
                        return self._send(code, {"error": {"message": f"Synthetic failure {code}"}})
                    rf = body.get("response_format")
                    if rf and fake.reject_schema:
                        return self._send(400, {"error": {"message": "response_format is not supported by this server"}})
                    if rf and fake.lmstudio and rf.get("type") == "json_object":
                        return self._send(400, {"error": "'response_format.type' must be 'json_schema' or 'text'"})
                    if fake.echo_400:
                        last = str(body["messages"][-1]["content"])
                        start = last.find("OCR TEXT:") + 10
                        return self._send(400, {"error": {"message": "Invalid request near: " + last[start:start + 60]
                                                          + " (Authorization: Bearer sk-local-SECRETKEY)"}})
                    content = fake._chat_text(body["messages"])
                    if rf and rf.get("type") == "json_schema" and "OCR TEXT" in json.dumps(body) and fake.raw_reply is None:
                        content = json.dumps(fake.analyze_reply)  # a server that honours the schema answers with JSON only
                    return self._send(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})
                if self.path.endswith("/v1/embeddings"):
                    inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
                    return self._send(200, {"data": [{"index": i, "embedding": embed(t)} for i, t in enumerate(inputs)]})
                if self.path.endswith("/api/chat"):
                    return self._send(200, {"message": {"content": fake._chat_text(body["messages"])}})
                if self.path.endswith("/api/embed"):
                    return self._send(200, {"embeddings": [embed(t) for t in body["input"]]})
                self._send(404, {"error": "not found"})

        return H
