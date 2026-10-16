"""Provider adapters for local AI servers.

* OpenAICompatible: LM Studio, llama.cpp server, vLLM, LocalAI, Jan ... (`<base>/models`, `/chat/completions`,
  `/embeddings`; base URL usually ends in /v1).
* Ollama: `<base>/api/tags`, `/api/chat`, `/api/embed`.

Every request first checks the endpoint's privacy class (see check_privacy): a profile marked Local or LAN
that resolves to a public address is refused, and External endpoints require explicit acknowledgement.
Requests ignore system proxy settings (trust_env=False) and never follow redirects, so traffic cannot be
silently routed to a cloud service. There is no fallback to any other provider.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
from urllib.parse import urlparse

import requests

from apps.core import crypto

CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale / carrier-grade NAT: treated as private LAN
RANK = {"local": 0, "lan": 1, "external": 2}


TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}
TRANSIENT_CATEGORIES = {"unavailable", "timeout"}


class AIError(Exception):
    """A failed AI step. ``category`` drives retry and display; ``status``/``server_message``/``capability`` carry the
    sanitized server answer (never document text or keys). ``transient`` failures may be retried a bounded number of
    times; everything else is deterministic and fails at once."""

    category = "other"

    def __init__(self, message: str, category: str | None = None, *, status: int | None = None,
                 server_message: str = "", capability: str = ""):
        super().__init__(message)
        if category:
            self.category = category
        self.status = status
        self.server_message = server_message
        self.capability = capability

    @property
    def transient(self) -> bool:
        return self.category in TRANSIENT_CATEGORIES

    def detail(self) -> dict:
        return {k: v for k, v in (("http_status", self.status), ("server_message", self.server_message),
                                  ("capability", self.capability)) if v}


_SECRETS = re.compile(r"(?i)(bearer\s+[\w.\-~+/]+=*|sk-[\w\-]{6,}|api[_-]?key[\"'=:\s]+[\w\-]{6,}|authorization[\"'=:\s]+\S+)")


def sanitize_server_message(raw: str, sent: str = "") -> str:
    """A short, safe version of an AI server's error text: no keys or tokens, and no stretch of the document text that
    was sent (servers sometimes echo the prompt in their error)."""
    msg = raw or ""
    try:
        data = json.loads(msg)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        err = data.get("error", data.get("message", data.get("detail", "")))
        if isinstance(err, dict):
            err = err.get("message") or err.get("msg") or json.dumps(err)[:300]
        msg = str(err or "")
    msg = " ".join(msg.split())[:400]
    msg = _SECRETS.sub("[removed]", msg)
    if sent and len(msg) >= 24:
        hay = " ".join(sent.split())
        out, i = [], 0
        while i < len(msg):  # drop any stretch of 24+ characters that also appears in what we sent (as long as it goes)
            w = msg[i:i + 24]
            if len(w) == 24 and w in hay:
                j = i + 24
                while j < len(msg) and msg[i:j + 1] in hay:
                    j += 1
                if not out or out[-1] != "[document text removed]":
                    out.append("[document text removed]")
                i = j
            else:
                out.append(msg[i])
                i += 1
        msg = "".join(out)
    return msg[:200].strip()


def _capability_in(message: str) -> str:
    """Change Set Y: does a 4xx answer name the optional structured-output feature (and nothing else)?"""
    low = message.lower()
    if "response_format" in low or "json_schema" in low or "json_object" in low or "structured output" in low:
        return "response_format"
    if "grammar" in low or ("format" in low and ("json" in low or "schema" in low)):  # llama.cpp grammar, Ollama "format"
        return "response_format"
    return ""


def strip_reasoning(text: str) -> str:
    """Reasoning models (Qwen3, DeepSeek-R1 ...) may put a <think>…</think> block before the answer."""
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "")
    if "<think>" in text.lower():  # an unterminated block: the answer was cut off inside the reasoning
        text = text[:text.lower().find("<think>")]
    return text.strip()


def classify_endpoint(base_url: str) -> str:
    """'local' (this host), 'lan' (private network) or 'external', from the resolved addresses."""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AIError("Enter a URL such as http://192.168.1.50:1234/v1", "config")
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise AIError(f"Cannot resolve {host}.", "unavailable")
    addrs = {ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos}
    if all(a.is_loopback for a in addrs):
        return "local"
    if all(a.is_loopback or a.is_private or a.is_link_local or (a.version == 4 and a in CGNAT) for a in addrs):
        return "lan"
    return "external"


def check_privacy(profile) -> str:
    actual = classify_endpoint(profile.base_url)
    if RANK[actual] > RANK.get(profile.privacy, 0):
        raise AIError(f"The endpoint is {actual.upper()} but the profile is marked {profile.privacy.upper()}. "
                      "Document text was not sent.", "privacy")
    if actual == "external" and not profile.external_acknowledged:
        raise AIError("External endpoints must be explicitly acknowledged by the administrator. Document text was not sent.", "privacy")
    return actual


class Provider:
    def __init__(self, profile):
        self.profile = profile
        self.base = profile.base_url.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False  # no system proxies: talk to the configured server directly
        key = crypto.decrypt(profile.api_key_enc) if profile.api_key_enc else ""
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}

    def _req(self, method: str, path: str, payload=None, timeout=None, *, url: str | None = None):
        check_privacy(self.profile)
        try:
            resp = self.session.request(method, url or f"{self.base}{path}", json=payload, headers=self.headers,
                                        timeout=timeout or self.profile.timeout_seconds, allow_redirects=False)
        except requests.Timeout:
            raise AIError("The AI server did not answer in time.", "timeout")
        except requests.ConnectionError:
            raise AIError("Cannot connect to the AI server. Is it running and reachable from this server?", "unavailable")
        if resp.status_code >= 300:
            raise self._http_error(resp, payload)
        try:
            return resp.json()
        except ValueError:
            raise AIError("The AI server sent a response that is not JSON.", "bad_response")

    @staticmethod
    def _http_error(resp, payload) -> AIError:
        """Change Set Y: classify an HTTP error and keep the server's own (sanitized) explanation. Only 408/425/429 and
        temporary 5xx are transient; a 4xx answer to the same request will not change on a retry."""
        status = resp.status_code
        sent = ""
        if isinstance(payload, dict):
            sent = " ".join(str(m.get("content", "")) for m in payload.get("messages") or [] if isinstance(m, dict))
        try:
            body = resp.text[:4000]
        except Exception:  # noqa: BLE001
            body = ""
        msg = sanitize_server_message(body, sent)
        tail = f" — {msg}" if msg else ""
        low = msg.lower()
        if status in (401, 403):
            return AIError("The AI server rejected the API key." + tail, "auth", status=status, server_message=msg)
        if status == 404 or ("model" in low and ("not found" in low or "does not exist" in low or "no models loaded" in low)):
            return AIError(f"Model or endpoint not found (HTTP {status}){tail}. Check the base URL and the model name.",
                           "model_missing", status=status, server_message=msg)
        if status in TRANSIENT_STATUS:
            return AIError(f"The AI server is busy or temporarily unavailable (HTTP {status}){tail}.", "unavailable",
                           status=status, server_message=msg)
        if status == 413 or "context" in low and ("length" in low or "exceed" in low or "too long" in low or "n_ctx" in low):
            return AIError(f"The request is too large for the model (HTTP {status}){tail}. Lower “Maximum input "
                           "characters” in the AI profile or load the model with a larger context.", "too_large",
                           status=status, server_message=msg)
        if 400 <= status < 500:
            return AIError(f"The AI server rejected the request (HTTP {status}){tail}.", "bad_request", status=status,
                           server_message=msg, capability=_capability_in(msg))
        return AIError(f"The AI server returned HTTP {status}{tail}.", "server_error", status=status, server_message=msg)

    # interface
    def list_models(self) -> list[str]:
        raise NotImplementedError

    def model_types(self) -> dict[str, str]:
        """{model id: 'llm' | 'vlm' | 'embeddings'} where the server says so; {} when it does not."""
        return {}

    def chat(self, messages: list[dict], model: str, *, json_mode: bool = False, image: bytes | None = None,
             schema: dict | None = None) -> str:
        raise NotImplementedError

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise NotImplementedError

    def structured(self, messages: list[dict], model: str, schema: dict) -> tuple[str, dict]:
        """Change Set Y: ask for JSON matching ``schema``. Uses the server's structured-output feature when it has one;
        if the server rejects that optional feature, makes ONE plain request that asks for JSON in the prompt and
        remembers the result for this profile (no loop). Returns (reply text, info)."""
        caps = dict(self.profile.capabilities or {}) if hasattr(self.profile, "capabilities") else {}
        if caps.get("structured_output") == "unsupported":
            return self.chat(messages, model), {"structured_output": "prompt", "fallback": False}
        try:
            reply = self.chat(messages, model, schema=schema)
            info = {"structured_output": "schema", "fallback": False}
            if caps.get("structured_output") != "supported":
                self._remember("structured_output", "supported")
            return reply, info
        except AIError as exc:
            # only an answer that names the optional feature (or a bare 400/422 with no explanation) is treated as
            # "not supported"; a malformed base request (unknown model, too large, ...) fails as it is
            if exc.category != "bad_request" or not (exc.capability or not exc.server_message):
                raise
            self._remember("structured_output", "unsupported")
            reply = self.chat(messages, model)
            return reply, {"structured_output": "prompt", "fallback": True, "rejected": exc.server_message or f"HTTP {exc.status}"}

    def _remember(self, key: str, value: str) -> None:
        p = self.profile
        if getattr(p, "pk", None) is None or not hasattr(p, "capabilities"):
            return
        caps = dict(p.capabilities or {})
        if caps.get(key) == value:
            return
        caps[key] = value
        p.capabilities = caps
        type(p).objects.filter(pk=p.pk).update(capabilities=caps)


class OpenAICompatible(Provider):
    def list_models(self):
        data = self._req("GET", "/models", timeout=min(15, self.profile.timeout_seconds))
        return sorted(m.get("id", "") for m in (data.get("data") or []) if m.get("id"))

    def model_types(self):
        """LM Studio also lists each model's type (llm, vlm, embeddings) under /api/v0/models. Other servers: {}."""
        root = self.base[:-3] if self.base.endswith("/v1") else self.base
        try:
            data = self._req("GET", "", timeout=min(10, self.profile.timeout_seconds), url=f"{root}/api/v0/models")
        except AIError:
            return {}
        return {m["id"]: str(m.get("type") or "") for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")}

    def chat(self, messages, model, *, json_mode=False, image=None, schema=None):
        msgs = [dict(m) for m in messages]
        if image is not None:
            uri = "data:image/png;base64," + base64.b64encode(image).decode()
            msgs[-1]["content"] = [{"type": "text", "text": msgs[-1]["content"]}, {"type": "image_url", "image_url": {"url": uri}}]
        payload = {"model": model, "messages": msgs, "temperature": 0.1, "max_tokens": self.profile.max_output_tokens, "stream": False}
        if schema is not None:
            # json_schema is what LM Studio, llama.cpp, vLLM and OpenAI accept; LM Studio rejects "json_object"
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "document_metadata", "schema": schema}}
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._req("POST", "/chat/completions", payload)
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise AIError("Unexpected chat response format.", "bad_response")
        if choice.get("finish_reason") == "length" and (schema is not None or not strip_reasoning(content)):
            raise AIError(f"The model's answer was cut off at the output limit ({self.profile.max_output_tokens} tokens). "
                          "Raise “Maximum output tokens” in the AI profile.", "too_large")
        return content

    def embed(self, texts, model):
        data = self._req("POST", "/embeddings", {"model": model, "input": texts})
        try:
            rows = sorted(data["data"], key=lambda r: r.get("index", 0))
            return [list(map(float, r["embedding"])) for r in rows]
        except (KeyError, TypeError, ValueError):
            raise AIError("Unexpected embedding response format.", "bad_response")


class Ollama(Provider):
    def list_models(self):
        data = self._req("GET", "/api/tags", timeout=min(15, self.profile.timeout_seconds))
        return sorted(m.get("name", "") for m in (data.get("models") or []) if m.get("name"))

    def chat(self, messages, model, *, json_mode=False, image=None, schema=None):
        msgs = [dict(m) for m in messages]
        if image is not None:
            msgs[-1]["images"] = [base64.b64encode(image).decode()]
        payload = {"model": model, "messages": msgs, "stream": False,
                   "options": {"temperature": 0.1, "num_predict": self.profile.max_output_tokens}}
        if schema is not None:
            payload["format"] = schema  # Ollama 0.5+ structured outputs; older servers reject it -> one prompt-only retry
        elif json_mode:
            payload["format"] = "json"
        data = self._req("POST", "/api/chat", payload)
        try:
            return (data.get("message") or {}).get("content") or ""
        except AttributeError:
            raise AIError("Unexpected chat response format.", "bad_response")

    def embed(self, texts, model):
        data = self._req("POST", "/api/embed", {"model": model, "input": texts})
        try:
            return [list(map(float, v)) for v in data["embeddings"]]
        except (KeyError, TypeError, ValueError):
            raise AIError("Unexpected embedding response format.", "bad_response")


def provider_for(profile) -> Provider:
    return Ollama(profile) if profile.provider == "ollama" else OpenAICompatible(profile)


def parse_json_object(text: str) -> dict:
    """Extract the first JSON object from a model reply (models sometimes wrap it in prose, code fences or a
    <think> block)."""
    text = strip_reasoning(text)
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start = text.find("{")
    if start < 0:
        raise AIError("The model did not return JSON.", "bad_response")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except ValueError:
                    break
                if isinstance(obj, dict):
                    return obj
                break
    raise AIError("The model returned malformed JSON.", "bad_response")
