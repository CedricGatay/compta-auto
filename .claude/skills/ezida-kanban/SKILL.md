---
name: ezida-kanban
description: Use this skill when the user wants to view, add, move, edit, or delete cards in their project's Kanban board stored in a `kanban.toml` file at the project root. Triggers include phrases like "add to my kanban", "what's in my todo", "move X to done", "show my board", "what's in [column]", or any time a `kanban.toml` file is mentioned or visible. Also use when the user expresses an idea, bug, or TODO during conversation and you want to offer adding it to the board. Do NOT use this skill to plan your own tasks — the Kanban belongs to the developer, not to you.
---

<!-- Source of truth for the embedded ezida skill. Edits to refs/SKILL.md are NOT propagated automatically; edit this file directly. -->

# Ezida — Project Kanban

## Philosophy

**This Kanban belongs to the developer, not to you.** Your role is to read, surface, and modify cards **only on explicit user request**. Do NOT add, edit, or delete cards on your own initiative based on what you think the developer should do, even when it feels helpful.

When the developer mentions an idea, bug, or TODO in conversation, do NOT silently add a card. Instead ask:

> "Want me to add this to your Kanban?"

Only proceed after explicit confirmation. Always confirm before destructive operations: delete, column rename, column removal, priority rename, priority removal.

## Before you act: discover the board structure

The user customizes columns and priorities. They are NOT always `todo/ongoing/done` or `low/medium/high` — a user might have `backlog/next/wip/review/done` or any other arrangement. Before any operation that references a column or priority by name, run:

```bash
ezida board
```

This returns the current structure. Cache the result for the rest of the conversation. Only re-run if the user explicitly modifies the board structure (adding, renaming, or removing a column or priority).

If the user asks to add a card to a column that does not exist (e.g. "add this to the backlog" but `backlog` is not in `columns`), do NOT silently fall back to another column. Ask:

> "You don't have a 'backlog' column. Want me to add one, or use [first existing column] instead?"

The same applies for priorities.

## File location

The board lives in `kanban.toml` at the project root. If the file does not exist and the user asks for a Kanban action, offer to initialize it with `ezida init` (defaults) or `ezida init --columns="backlog,todo,done"` for a custom setup.

## How to invoke ezida

If the `ezida` command is in the PATH (installed via the install script), use it directly.

```bash
ezida <command> [args]
```

All commands accept `--json` for structured output, which you should prefer when parsing results.

### Reading
```bash
ezida board                          # board structure: columns, priorities, counts
ezida list                           # all cards, compact
ezida list --column=todo             # filter by column
ezida list --title-contains=auth     # filter by title substring
ezida list --tag=security            # filter by tag
ezida list --priority=high           # filter by priority
ezida get <id>                       # full details for one card
```

### Writing
```bash
ezida add "Title" --column=todo [--priority=high] [--tags=a,b] [--description="..."]
ezida edit <id> [--title="..."] [--description="..."] [--priority=...] [--tags=...]
ezida move <id> <column>
ezida rm <id>
```

### Viewer (browser UI)
```bash
ezida serve                          # bind 127.0.0.1:7777, open default browser
ezida serve --no-open                # bind without opening the browser
ezida serve --port=9000              # custom starting port (auto-fallback +10)
```

The viewer is a single-page web UI for the same `kanban.toml`. It supports drag-to-move cards, click-to-edit fields in a detail modal, inline column-foot composer (`+ Add a card`), hover-to-delete `×` on cards, an inline column rename / add / delete / drag-reorder, a topbar substring filter, and a 3-state light / system / dark theme toggle. Edits to `kanban.toml` from any source (CLI in another terminal, manual file edit) propagate to the open viewer via SSE within ~1 s.

The server binds 127.0.0.1 only — never exposed to the network. It exits on `SIGINT` / `SIGTERM` with a 5 s drain.

If the user asks "show me my board in the browser" or similar, offer:

> "Want me to start the viewer? It binds 127.0.0.1:7777 and opens your browser automatically."

If the user has already started the server in another terminal and just wants the URL opened, prefer `open http://127.0.0.1:7777` (macOS) / `xdg-open http://127.0.0.1:7777` (Linux) over re-running `ezida serve`.

### Board config
```bash
ezida init [--columns="a,b,c"] [--priorities="low,med,high"]
ezida columns add <name> [--position=N]
ezida columns rename <old> <new>     # propagates to all cards automatically
ezida columns rm <name>              # fails if cards still reference it

ezida priorities add <name>
ezida priorities rename <old> <new>  # propagates to all cards automatically
ezida priorities rm <name>           # fails if cards still reference it
```

## Schema reference

```toml
schema_version = 1

[board]
columns = ["todo", "ongoing", "done"]    # left-to-right display order
priorities = ["low", "medium", "high"]   # ascending: low → high

[[cards]]
id = "a3f2k9"                  # 6 chars from [0-9a-z], unique board-wide
title = "Card title"            # non-empty
column = "todo"                 # must match a value in [board].columns
description = """               # multi-line, may be empty
Optional description.
"""
created_at = 2026-05-20T14:30:00Z   # ISO 8601 UTC, set once at creation
updated_at = 2026-05-20T14:30:00Z   # ISO 8601 UTC, refreshed on any change
tags = ["security"]             # array of strings, may be empty
priority = "high"               # optional; must match [board].priorities if present
```

## Manual editing (last-resort fallback)

If neither `ezida` nor Python is available, edit `kanban.toml` directly with precise edits. Rules:

- **Card order in the file = card order in its column.** Place `[[cards]]` blocks at the desired position.
- **`id`**: generate 6 random chars from `[0-9a-z]`. Verify uniqueness across all cards before assigning.
- **`updated_at`**: refresh to the current UTC timestamp on any modification.
- **`column` and `priority`**: must reference values defined in `[board]`.
- **Renaming a column or priority in `[board]`**: also propagate the new name to every referencing card in the same edit.
- **Removing a column or priority** still referenced by cards: refuse. List the affected cards and ask the user how to proceed.

## Common patterns

### "What's on my board?"
1. `ezida board` (if not cached) to know the columns.
2. `ezida list --json` once, group results client-side.
3. Report compactly, one line per column. Don't dump descriptions unless asked.

### "Add this to my kanban"
1. `ezida board` if not already known this session.
2. Confirm the target column with the user (default: first column).
3. Ask about priority and tags only if the user hasn't specified and they seem relevant.
4. `ezida add "..." --column=... [other flags]`.

### "Move X to [column]"
1. If the user gives a title or partial title (not an id), run `ezida list --title-contains=X` to disambiguate.
2. Confirm the right card with the user if multiple match.
3. `ezida move <id> <column>`.

### Surfacing an idea mentioned in conversation
The user says: *"I should refactor that auth flow at some point."*

Do NOT add a card. Reply:

> "Want me to add 'Refactor auth flow' as a card to your Kanban?"

Only act on a clear yes.

## Output style

When reporting multiple cards, prefer one compact line per column:

```
todo (3): a3f2k9 Refactor auth · b7m1p4 Update README · c4q9z2 Add tests
ongoing (1): d8x1m7 Migrate to SwiftUI [high]
done (12 — most recent): …
```

For a single card detail, show: id, title, column, priority, tags, description, created_at, updated_at.
