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
import socket
from urllib.parse import urlparse

import requests

from apps.core import crypto

CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale / carrier-grade NAT: treated as private LAN
RANK = {"local": 0, "lan": 1, "external": 2}


class AIError(Exception):
    category = "other"

    def __init__(self, message: str, category: str | None = None):
        super().__init__(message)
        if category:
            self.category = category


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

    def _req(self, method: str, path: str, payload=None, timeout=None):
        check_privacy(self.profile)
        try:
            resp = self.session.request(method, f"{self.base}{path}", json=payload, headers=self.headers,
                                        timeout=timeout or self.profile.timeout_seconds, allow_redirects=False)
        except requests.Timeout:
            raise AIError("The AI server did not answer in time.", "timeout")
        except requests.ConnectionError:
            raise AIError("Cannot connect to the AI server. Is it running and reachable from this server?", "unavailable")
        if resp.status_code in (401, 403):
            raise AIError("The AI server rejected the API key.", "auth")
        if resp.status_code == 404:
            raise AIError("Endpoint or model not found on the AI server (check the base URL and model name).", "model_missing")
        if resp.status_code >= 300:
            raise AIError(f"The AI server returned HTTP {resp.status_code}.", "unavailable")
        try:
            return resp.json()
        except ValueError:
            raise AIError("The AI server sent a response that is not JSON.", "bad_response")

    # interface
    def list_models(self) -> list[str]:
        raise NotImplementedError

    def chat(self, messages: list[dict], model: str, *, json_mode: bool = False, image: bytes | None = None) -> str:
        raise NotImplementedError

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise NotImplementedError


class OpenAICompatible(Provider):
    def list_models(self):
        data = self._req("GET", "/models", timeout=min(15, self.profile.timeout_seconds))
        return sorted(m.get("id", "") for m in (data.get("data") or []) if m.get("id"))

    def chat(self, messages, model, *, json_mode=False, image=None):
        msgs = [dict(m) for m in messages]
        if image is not None:
            uri = "data:image/png;base64," + base64.b64encode(image).decode()
            msgs[-1]["content"] = [{"type": "text", "text": msgs[-1]["content"]}, {"type": "image_url", "image_url": {"url": uri}}]
        payload = {"model": model, "messages": msgs, "temperature": 0.1, "max_tokens": self.profile.max_output_tokens, "stream": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._req("POST", "/chat/completions", payload)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise AIError("Unexpected chat response format.", "bad_response")

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

    def chat(self, messages, model, *, json_mode=False, image=None):
        msgs = [dict(m) for m in messages]
        if image is not None:
            msgs[-1]["images"] = [base64.b64encode(image).decode()]
        payload = {"model": model, "messages": msgs, "stream": False,
                   "options": {"temperature": 0.1, "num_predict": self.profile.max_output_tokens}}
        if json_mode:
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
    """Extract the first JSON object from a model reply (models sometimes wrap it in prose or code fences)."""
    text = (text or "").strip()
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
