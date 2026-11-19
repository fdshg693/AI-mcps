---
paths:
  - "memo/src/memo/service/**"
---

## memo — Domain features (memo / user / category)

`service/*` is the DRY home for cross-edge domain invariants (both MCP tools and the web UI go through it): memo `title` required + trim + category-must-be-registered; user `name` required + immutable + last-admin-can't-be-deleted/demoted; category name required + `OTHERS` protected + rename/delete cascades to memos via DB triggers (not app SQL).

- Memo access is always scoped to the connected user's `user_id` — **no cross-user mode, not even for admins**. Semantic search (`service.memo.semantic_search`) is the only domain layer allowed to make network calls (OpenAI embeddings), cached in `memo_embeddings`. Details: [claude/features/memo.md](../../memo/claude/features/memo.md).
- User switching (`switch_user`) separates a stable client identity (stdio: process-level; HTTP: `?client_id=`, not `Mcp-Session-Id` which changes on reconnect) from the mutable current user, and drives admin-tool visibility. Details: [claude/features/user.md](../../memo/claude/features/user.md).
- Categories are a first-class per-user table, not just a memo column; `OTHERS` is the un-deletable default. Details: [claude/features/category.md](../../memo/claude/features/category.md).
