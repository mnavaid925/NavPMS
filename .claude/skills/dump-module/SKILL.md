---
name: dump-module
description: Regenerate the consolidated <NN>_<slug>.txt code dump for one (or all) NavPMS modules into the temp/ folder. The .txt file contains every backend file from apps/<name>/ followed by every frontend template from templates/<name>/, with per-file separators. Use when the user says "dump module X", "regenerate the temp file for X", "extract code for module X", "give me a code dump of X", or invokes /dump-module. The user can pass a module number (1-13), an app folder name (tenants/portal/requisitions/approvals/vendors/sourcing/rfx/auctions/contracts/catalog/purchase_orders/fulfillment/goods_receipt), a friendly name (e.g. "rfx", "fulfillment"), or "all" to regenerate every module.
---

# dump-module — NavPMS module code-dump generator

This skill regenerates one (or all) of the consolidated `temp\<NN>_<slug>.txt` files that contain a single module's complete backend + frontend source code, for use in code review, hand-off, AI prompts, or archival.

## When to use

- User says: "dump module X", "regenerate temp file for X", "extract module X code", "give me the .txt for X", "refresh the rfx module dump", "rebuild all module dumps"
- User invokes `/dump-module` (with or without an argument)
- User explicitly references the `temp/` folder code dumps

## When NOT to use

- User wants documentation written for a module → use the README maintenance rule and edit `README.md`
- User wants automated tests for a module → use `/sqa-review`
- User wants a manual click-through test → use `/manual-test`
- User wants a code review → use `/review` or `/sqa-review`

## Inputs

The skill takes ONE positional argument — the module identifier. Accepted forms:

| Form                | Examples                                     |
|---------------------|----------------------------------------------|
| Module number       | `1`, `7`, `13`, `01`, `09`                   |
| App folder name     | `tenants`, `portal`, `requisitions`, `approvals`, `vendors`, `sourcing`, `rfx`, `auctions`, `contracts`, `catalog`, `purchase_orders`, `fulfillment`, `goods_receipt` |
| Friendly keyword    | `supplier`, `po`, `grn`, `rfq`, `eauction`, `shipping` |
| Bulk                | `all` (or `*`) — regenerates all 13 modules  |

If the user does NOT specify a module, ask them which one (single-select) before running the script — do not guess.

## How to run

The skill ships a single PowerShell script: `.claude\skills\dump-module\dump_module.ps1`. Invoke it via the **PowerShell** tool (the user is on Windows PowerShell 5.x):

```
& '.claude\skills\dump-module\dump_module.ps1' -Module <identifier>
```

Examples:

```
& '.claude\skills\dump-module\dump_module.ps1' -Module rfx
& '.claude\skills\dump-module\dump_module.ps1' -Module 7
& '.claude\skills\dump-module\dump_module.ps1' -Module fulfillment
& '.claude\skills\dump-module\dump_module.ps1' -Module all
```

Notes:
- The script auto-creates `temp/` if missing.
- The script overwrites the matching `<NN>_<slug>.txt` file (idempotent — safe to re-run).
- `temp/` is gitignored — no commit snippet needed for the generated `.txt`.
- The script prints one line per generated file: `OK  <slug>  <bytes>  ->  temp\<slug>.txt`.

## Output structure (per .txt file)

```
####################################################################################################
# MODULE <number>. <Title>
# Backend:  apps\<name>\
# Frontend: templates\<name>\
# Generated: <YYYY-MM-DD HH:MM:SS>
####################################################################################################

====================================================================================================
BACKEND  (apps\<name>\)
====================================================================================================

----------------------------------------------------------------------------------------------------
FILE: apps\<name>\admin.py
----------------------------------------------------------------------------------------------------
<file contents>

... (one block per .py / .json / .yml / .md / .ini file, sorted by full path, __pycache__ excluded)

====================================================================================================
FRONTEND  (templates\<name>\)
====================================================================================================

----------------------------------------------------------------------------------------------------
FILE: templates\<name>\dashboard.html
----------------------------------------------------------------------------------------------------
<file contents>

... (one block per .html / .htm / .js / .css / .txt file, sorted by full path)
```

## Module registry (kept in `dump_module.ps1`)

Real module numbers follow `PMS.md` (the spec's `### N` headers are offset +1 — `### 11` = real Module 12). Modules 14–20 in the spec are not yet built, so they are not in the registry.

| # | Slug                                    | apps\             | templates\        |
|---|-----------------------------------------|-------------------|-------------------|
| 1 | `01_tenant_subscription_management`     | `tenants`         | `tenants`         |
| 2 | `02_user_dashboard_portal`              | `portal`          | `portal`          |
| 3 | `03_requisition_management`             | `requisitions`    | `requisitions`    |
| 4 | `04_approval_workflow_engine`           | `approvals`       | `approvals`       |
| 5 | `05_vendor_management`                  | `vendors`         | `vendors`         |
| 6 | `06_sourcing_tendering`                 | `sourcing`        | `sourcing`        |
| 7 | `07_rfx_management`                     | `rfx`             | `rfx`             |
| 8 | `08_eauction_management`                | `auctions`        | `auctions`        |
| 9 | `09_contract_management`                | `contracts`       | `contracts`       |
| 10 | `10_catalog_management`                | `catalog`         | `catalog`         |
| 11 | `11_purchase_order_management`         | `purchase_orders` | `purchase_orders` |
| 12 | `12_order_fulfillment_tracking`        | `fulfillment`     | `fulfillment`     |
| 13 | `13_goods_receipt_inspection`          | `goods_receipt`   | `goods_receipt`   |

If a new module is added to the codebase later, append a row to the `$registry` and `$aliases` blocks in `dump_module.ps1` so this skill can dump it.

## After running

1. Show the user the printed `OK ... bytes` line(s).
2. Confirm the path: `temp\<slug>.txt`.
3. Do NOT propose a git commit for the .txt file — `temp/` is gitignored.
4. If the script reports "no backend folder found" or "no frontend folder found" for a module, surface that warning to the user — it usually means the module hasn't been built yet or the folder name in the registry is stale.

## Workflow checklist

1. Resolve the module identifier from the user's request. If ambiguous, ask via `AskUserQuestion`.
2. Invoke the PowerShell script via the PowerShell tool with the resolved identifier.
3. Relay the script's `OK ... bytes` output to the user verbatim.
4. End the turn — no commits, no follow-up unless the user asks for more.
