# ADR-0003: Capability bitmask with folder inheritance and explicit exceptions

- Status: accepted

## Decision
`AccessRule` grants a capability bitmask on a folder or document to a user or family group. Effective folder capabilities = own rules ∪ delegation-derived grants ∪ (parent's effective capabilities if the folder inherits). Documents add their own rules ∪ (folder's capabilities if inheriting). Breaking inheritance creates an exception. The main administrator has all capabilities. Default deny. Archived items are visible only to the main administrator.

Owners receive an explicit, visible rule on their personal root at setup (not an implicit owner privilege), so access is always explainable. Delegation scopes map to capabilities on folders owned by members of the delegated group; delegates cannot grant beyond what they hold or grant *Manage*; folder/document moves that change inheritance require *Manage*.

## Consequences
`AccessContext` loads the folder tree and the user's rules once per request (cheap for family-scale data) and produces both querysets and explanations. All routes return 404 for inaccessible objects.
