---
name: dump-module
description: Regenerate the consolidated <NN>_<slug>.txt code dump for one (or all) NavMSM modules into the temp/ folder. The .txt file contains every backend file from apps/<name>/ followed by every frontend template from templates/<name>/, with per-file separators. Use when the user says "dump module X", "regenerate the temp file for X", "extract code for module X", "give me a code dump of X", or invokes /dump-module. The user can pass a module number (1-12), an app folder name (tenants/plm/bom/pps/mrp/mes/qms/inventory/procurement/eam/labor/cost), a friendly name (e.g. "cost", "mes"), or "all" to regenerate every module.
---

# dump-module — NavMSM module code-dump generator

This skill regenerates one (or all) of the consolidated `temp\<NN>_<slug>.txt` files that contain a single module's complete backend + frontend source code, for use in code review, hand-off, AI prompts, or archival.

## When to use

- User says: "dump module X", "regenerate temp file for X", "extract module X code", "give me the .txt for X", "refresh the cost module dump", "rebuild all module dumps"
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
| Module number       | `1`, `4`, `12`, `01`, `09`                   |
| App folder name     | `tenants`, `plm`, `bom`, `pps`, `mrp`, `mes`, `qms`, `inventory`, `procurement`, `eam`, `labor`, `cost` |
| Friendly keyword    | `quality`, `supplier`, `asset`, `workforce`, `accounting` |
| Bulk                | `all` (or `*`) — regenerates all 12 modules  |

If the user does NOT specify a module, ask them which one (single-select) before running the script — do not guess.

## How to run

The skill ships a single PowerShell script: `.claude\skills\dump-module\dump_module.ps1`. Invoke it via the **PowerShell** tool (the user is on Windows PowerShell 5.x):

```
& '.claude\skills\dump-module\dump_module.ps1' -Module <identifier>
```

Examples:

```
& '.claude\skills\dump-module\dump_module.ps1' -Module pps
& '.claude\skills\dump-module\dump_module.ps1' -Module 12
& '.claude\skills\dump-module\dump_module.ps1' -Module cost
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

| # | Slug                                        | apps\           | templates\      |
|---|---------------------------------------------|-----------------|-----------------|
| 1 | `01_tenant_subscription_management`         | `tenants`       | `tenants`       |
| 2 | `02_product_lifecycle_management`           | `plm`           | `plm`           |
| 3 | `03_bill_of_materials`                      | `bom`           | `bom`           |
| 4 | `04_production_planning_scheduling`         | `pps`           | `pps`           |
| 5 | `05_material_requirements_planning`         | `mrp`           | `mrp`           |
| 6 | `06_shop_floor_control_mes`                 | `mes`           | `mes`           |
| 7 | `07_quality_management`                     | `qms`           | `qms`           |
| 8 | `08_inventory_warehouse_management`         | `inventory`     | `inventory`     |
| 9 | `09_procurement_supplier_portal`            | `procurement`   | `procurement`   |
| 10 | `10_equipment_asset_management`            | `eam`           | `eam`           |
| 11 | `11_labor_workforce_management`            | `labor`         | `labor`         |
| 12 | `12_cost_management_accounting`            | `cost`          | `cost`          |

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
