# Local AI (optional)

## What it does {#overview}

Local AI adds suggestions and question answering on top of the normal document features, using an AI server **you** run,
such as LM Studio or Ollama on a PC in your home. It is off by default and never required:
- Uploads, OCR (Tesseract), full-text search, reminders, sharing, backup and sign-in work exactly the same without it.
- They keep working if the AI server is switched off, slow or returns nonsense.

| Feature | What you get |
|---|---|
| **OCR assist** | Suggested title, issue/expiry date, document number and a one-line summary from the OCR text (or the image, with a vision model). |
| **Smart organisation** | Suggested document type, issuer, tags and folder. |
| **Document assistant** | Ask questions such as "When does my passport expire?" and get an answer with links to the documents used. |
| **Semantic search** | "Match meaning (AI)" in search finds documents with similar meaning, not only the same words. |

## How it works {#architecture}

Upload → file checks → original stored → text extraction / OCR (as the OCR policy allows) → *(optional)* AI analysis → **suggestions** → you review →
accepted values saved → search, reminders and assistant use them.

The **OCR engine** and the **AI model** are two separate choices:

| Part | What it does | Where it is chosen |
|---|---|---|
| OCR engine: **Tesseract** or **PaddleOCR (PP-OCRv5)** | Reads the text of a scan or photo, on this server | Settings → OCR & processing |
| **Text model** | Reads that text and proposes metadata; answers the assistant | The AI profile |
| **Embedding model** | Turns text into vectors for semantic search; never writes answers | The AI profile |
| **Vision model** (optional) | Not used by Analyze Document | The AI profile |

You can switch the OCR engine at any time without touching the AI profile.

- AI never changes a document by itself. Title, type, owner, folder, dates, reminders, tags, issuer and confirmed details only
  change when someone with edit rights clicks **Accept**. Accepting goes through the same checks as editing by hand, and accepted dates become
  confirmed details that drive reminders.
- AI work runs as background jobs after the document is safely stored, with a configurable limit (default one at a time) so it
  never slows down normal processing.
- There is **no fallback to any cloud service**. If the configured server is unavailable, the AI feature simply reports that.

## Turning it on {#enable}

1. Run an AI server on your network (examples below).
2. **Settings → Local AI → Add AI profile**: enter the server URL and models, click **Test connection**.
3. Switch on **Local AI enabled** and the features you want.

People see AI suggestions on documents they can edit, **Ask AI** in the menu and **Match meaning** in search.

## AI profiles {#profiles}

A profile is one AI server connection:
- **name and connection type:** OpenAI-compatible or Ollama
- **server URL**
- **API key:** optional, stored encrypted and never shown again
- **models:** text, vision and embedding
- **limits:** timeout, maximum text sent and maximum reply length
- **privacy class** (see below)
- **which features it may serve**
- **default:** the default profile serves the features

**Test connection** checks, step by step, the privacy class, reachability, the model list, that the **text model** exists and is a
chat model, that the **embedding model** exists and returns a vector, and the optional vision model. **Test AI analysis** sends a
small synthetic text document (no family data) through exactly the same path as Analyze Document and shows what came back. See
[Diagnostics](#diagnostics).

The text model and the embedding model must be different models; a name containing “embed” is refused as the text model.

### LM Studio (or other OpenAI-compatible servers) {#lm-studio}

On a PC with a decent GPU or Apple Silicon:
1. Install LM Studio and download, for example, a 7–8B instruct model and an embedding model such as `nomic-embed-text`.
2. **Developer → Start server**, enable "Serve on local network".
3. Profile: connection type *OpenAI-compatible*, URL `http://<pc-ip>:1234/v1`, privacy *Private LAN*.

llama.cpp `llama-server`, vLLM, LocalAI and Jan work the same way (URL ending in `/v1`).

Choose a chat/instruct model as the **text model** (for example `qwen3-8b`) and the embedding model separately (for example
`text-embedding-nomic-embed-text-v1.5`). Personal DM asks for JSON with the server's *structured output* feature
(`response_format` of type `json_schema`), which LM Studio, llama.cpp, vLLM and OpenAI support. A server that rejects it gets one
plain request asking for JSON in the prompt instead, and the profile remembers this (shown under the profile as
*Structured output: not supported*). Reasoning models that write a `<think>` block first are fine: the block is ignored. If such a
model's answer is cut off, raise *Max reply (tokens)* in the profile.

### Ollama {#ollama}

```
ollama pull llama3.1:8b
ollama pull nomic-embed-text
OLLAMA_HOST=0.0.0.0 ollama serve
```

Profile: connection type *Ollama*, URL `http://<pc-ip>:11434`, text model `llama3.1:8b`, embedding model `nomic-embed-text`.

### Model discovery {#discovery}

After saving a profile, **Discover models on the server** fills the model fields with what the server offers
(`/v1/models` or Ollama's `/api/tags`).

## Privacy classes {#privacy}

| Class | Meaning |
|---|---|
| **Local only** | The AI server runs on this server, next to the app. |
| **Private LAN** | Another machine on your private network (RFC 1918, link-local or Tailscale/CGNAT addresses). |
| **External endpoint** | Anything else. Requires ticking "I understand that selected document content may leave the local network". |

Before **every** request the server's real address is resolved and compared with the profile's class. A "Private LAN"
profile whose name resolves to a public address is refused and no text is sent. Requests ignore system proxy settings and
never follow redirects.

## OCR assist {#ocr-assist}

After processing (if *Analyse new uploads automatically* is on), or with **Analyse again** on a document, the model gets the OCR text
(up to *Max text sent* per request). This happens only for document types where **AI may read text** is allowed in Settings → OCR & processing
(or, for documents without a type, the *Untyped documents* setting); other documents are skipped by re-indexing and **Analyse** is
refused. The AI never receives every upload by default; see [Local AI and OCR text](ocr-corrections.md#ai). It returns suggestions shown under **AI suggestions** in the document's details:

- **Accept**, **Dismiss** or **Accept all**.
- Document numbers are only suggested if they literally appear in the text.
- Details a person entered or corrected by hand are never proposed for replacement.
- The model always receives **text**, never the file or a page image.

## Analyze Document step by step {#pipeline}

1. **Preparing:** the document is checked (permissions, antivirus quarantine, AI allowed for its type).
2. **OCR:** the current text is reused when it is usable (text layer or an earlier OCR run of this file). Otherwise, when you
   chose **Analyse**, text recognition is queued with the configured engine (Tesseract or PaddleOCR) and the analysis continues by
   itself when recognition finishes. Automatic analysis after an upload never starts OCR for a type set to manual OCR.
3. **Checking OCR text:** if recognition found no usable text, the job stops with *OCR completed, but no usable text was detected.*
   The AI server is **not** called.
4. **AI analysis:** the text goes to the profile's **text model**. A long document is analysed in up to three parts, in page order;
   if text remains after that, the job says how much was analysed.
5. **Checking AI answer:** only the requested fields with valid values (real dates, known types and folders) are kept; an answer
   that is not JSON or has none of the fields fails here.
6. **Saving suggestions**, then **done**.

**Retries:** a timeout, a lost connection, HTTP 429 or a temporary 5xx error is retried automatically, at most three attempts in all
(after 1 and 5 minutes); the job shows *queued · retry 2 of 3 at …*. Everything else, such as a rejected request (HTTP 400), an
unknown model, an empty OCR result or an invalid answer, fails at once with its stage and reason and is **not** queued again. After
fixing the cause, press **Retry** in the job list or **Analyse again** on the document. A document never has more than one queued
analysis.

## Smart organisation {#smart-organization}

Suggests a document type and issuer from your existing lists, up to three new tags, and a folder you are allowed to move the
document into. Accepting a folder moves the document with the normal move permission check.

## Document assistant {#assistant}

**Ask AI** (menu) or **Ask AI about this document** (document details). Examples:
- "Find my passport"
- "When does my passport expire?"
- "Which of my documents expire within six months?"
- "Summarise this insurance policy"
- "Which documents are missing an expiry date?"

Answers link to the documents used. If the AI server is down you still get the list of matching documents. Always check
important details in the document itself.

## Semantic search {#semantic-search}

With **Semantic search** on and an embedding model configured, each document's text is split into chunks and turned into
embeddings when it is processed. After turning it on, use **Rebuild semantic index** (Settings → Local AI → AI jobs) for
existing documents. New versions replace old embeddings, and deleting a document deletes them. Normal full-text search keeps working when
semantic search is unavailable.

## Permissions {#permissions}

AI does not create a new way around permissions:

- The assistant and semantic search start from the list of documents the signed-in person may open, using the same check as browsing and
  search. Documents they cannot open are never read, sent to the model, scored or counted, so the AI cannot reveal their
  content, snippets, metadata or existence.
- Revoking access takes effect immediately, because filtering happens at question time.
- Citations to anything outside the permitted set are removed from answers.
- Only people who can edit a document can analyse it or accept suggestions.
- **Who may use AI**: everyone (each on their own permitted documents) or administrators only. The main administrator can
  switch each feature, or all AI, off at any time.

## Resources {#resources}

A 2 vCPU / 4 GB LXC cannot run useful language models itself. Run the AI server on a separate PC or server on your LAN and
connect to it. Keep **Parallel AI jobs** at 1 on small containers. Analysis of one document typically takes 5–60 seconds
depending on the model and hardware.

## Diagnostics {#diagnostics}

Settings → Local AI has four separate tests, so you can tell whether OCR or AI is failing:

| Test | Checks |
|---|---|
| **Test connection** (per profile) | Server reachable, privacy class, model list, text model, embedding model, optional vision model |
| **Test AI analysis** (per profile) | A synthetic text document through the Analyze Document path, with the structured-output fallback |
| **Test OCR — Tesseract** | Recognition of a generated sample image |
| **Test OCR — PaddleOCR** | The same with PaddleOCR |

## Troubleshooting {#troubleshooting}

| Message | What to do |
|---|---|
| failed · AI analysis: The AI server rejected the request (HTTP 400) — … | The text after the dash is the server's own explanation (document text and keys removed). Run **Test AI analysis**. A message about `response_format` is handled automatically from this release on; for others, check the model and the limits in the profile. |
| failed · AI analysis: Model or endpoint not found | The text model name does not exist on the server, or no model is loaded. Use **Discover models** and **Test connection**. |
| The request is too large for the model | Lower *Max text sent* in the profile, or load the model with a larger context in LM Studio. |
| The model's answer was cut off at the output limit | Raise *Max reply (tokens)* (reasoning models need more). |
| failed · OCR: OCR completed, but no usable text was detected | The scan is blank, unreadable or too small. Try **Run OCR** with the other engine or a better scan. The AI was not called. |
| failed · OCR: OCR failed: … | Run **Test OCR** for that engine; see the OCR guide. |
| queued · retry 2 of 3 at … | The server was busy or unreachable; the job retries by itself. |
| Cannot connect to the AI server | Is the server running and listening on the network (LM Studio "Serve on local network", `OLLAMA_HOST=0.0.0.0`)? Firewall on the PC? |
| The endpoint is EXTERNAL but the profile is marked LAN | The URL resolves to a public address. Use the LAN address, or change the class deliberately. |
| The model did not return JSON | Use a larger or instruction-tuned model, then **Retry**. |
| The AI server did not answer in time | Increase the profile timeout or use a smaller model. |

**Settings → Local AI → AI jobs** shows each job's type, who requested it, profile/model, status, the stage it reached or failed
at, the OCR engine and character count, and the HTTP status, without document content. *AI diagnostic logging* logs request
and response **sizes** only; prompts and answers are never logged.

## Backups {#backup}

AI profiles (with the encrypted API key), suggestions and embeddings are part of the database backup. Embeddings can always be rebuilt.
