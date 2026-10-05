# ADR-0008: Optional Local AI as an advisory layer with permission-filtered retrieval

- Status: accepted (change set 2026-10)

## Decision
- Provider adapters for OpenAI-compatible servers and Ollama behind one small interface (list_models, chat, embed). No vendor SDKs.
- Privacy classes (Local / LAN / External) are checked against the endpoint's resolved addresses before every request.
  `requests` ignores system proxies and redirects. No fallback to any other provider.
- AI output is stored as `AISuggestion` rows. Accepting one calls the same services and permission checks as a manual edit;
  accepted dates become confirmed fields, the only values that drive reminders.
- Retrieval for the assistant and semantic search starts from `AccessContext.documents()`. Unauthorised documents are never
  read, embedded into prompts, scored or counted. Embeddings are stored in PostgreSQL (`ArrayField`) and compared in Python
  only for the permitted set, which is adequate for a family-sized library and needs no extension.
- AI runs as `ai_task` jobs after baseline processing, limited by `ai.max_parallel`. `AIJob` keeps safe metadata only.

## Consequences
Answer quality depends on the family's own model. Semantic search scales linearly with permitted chunks; pgvector could be
added later behind the same function if libraries grow very large.
