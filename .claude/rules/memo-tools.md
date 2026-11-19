---
paths:
  - "memo/src/memo/server/**"
---

## memo — Layering / MCP tools / Admin visibility

Layer direction: `server/{mcp,web}` (transport edges) → `service/*` → `repository/*` → `infra/*`, one-way. Transport edges always go through `service/*` for domain data — never `repository/*` directly (the one exception: `authz.resolve_caller()` / `switch_user` call `repository.user.get_user_db` directly for identity lookup). The MCP edge adds an authorization step: `tools/* → authz → service/* → infra`.

15 MCP tools: 7 memo, 2 category (create/list only — no update/delete over MCP), 5 user-management (admin-only), 1 session (`switch_user`). The 5 admin tools are tagged and hidden by default via FastMCP's official **Component Visibility API** (`mcp.disable(tags=...)` server-level + `ctx.enable_components()`/`disable_components()` per-session in `admin_tools.py`) — **not** hand-rolled middleware; do not reimplement this with a `tools/list`-filtering middleware. `switch_user` toggles visibility for that session based on the target's `is_admin` flag.

Full tool table, args, and the visibility mechanism: [claude/TOOLS.md](../../memo/claude/TOOLS.md) and [claude/features/user.md](../../memo/claude/features/user.md). Module-by-module responsibilities: [claude/FOLDER_STRUCTURE.md](../../memo/claude/FOLDER_STRUCTURE.md).
