---
paths:
  - "memo/src/memo/infra/**"
  - "memo/src/memo/migrations/**"
  - "memo/src/memo/repository/**"
---

## memo — Schema / DB / Migrations

SQLite (WAL). `users.id` (immutable) is what `memos`/`categories` reference via `user_id` — `users.name` is just a mutable login handle. Admin status is the independent `users.is_admin` flag, not the name. FKs are always `ON` with `ON DELETE CASCADE` (deleting a user cascades memos/categories/embeddings); the `memo ⇄ category` link is a denormalized string kept in sync by two triggers (rename cascade, delete → reassign to `OTHERS`), not an FK, because delete behavior is per-row dynamic.

Schema changes are version-managed migrations in `migrations/` (`schema_version` table + `_MIGRATIONS` registry, modeled on `dynamic_prompt`). A migration must be a frozen snapshot — never import a helper whose definition can later change (see `m001` inlining its own trigger SQL).

Full table definitions, the migration-adding recipe, and the `m001`/`m002` migration history: [claude/SCHEMA.md](../../memo/claude/SCHEMA.md). Module responsibilities and the repository↔infra↔migrations import direction: [claude/FOLDER_STRUCTURE.md](../../memo/claude/FOLDER_STRUCTURE.md).
