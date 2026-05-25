# Module 4 (Approvals) — Manual Test Defect Fixes

Follow-up to [.claude/manual-tests/approvals-manual-test.md](../manual-tests/approvals-manual-test.md).
Fix the candidate defects pre-flagged in the test plan, then update the plan
to reflect the new expected behaviour.

## Defects

| ID | TC | Severity | Defect | Fix location |
|----|----|----------|--------|--------------|
| D-01 | TC-NEG-03 | Low | `ApprovalRuleForm` accepts negative `min_amount` / `max_amount`. Negative thresholds will never match a real requisition (`total >= min_amount` always true / `total <= max_amount` always false) — silently broken rule. | [apps/approvals/forms.py](../../apps/approvals/forms.py) |
| D-02 | TC-CREATE-04 | Low | `ApprovalRuleForm` accepts `min_amount > max_amount`. Saves successfully but `matches()` returns False for every requisition — silently dead rule. | [apps/approvals/forms.py](../../apps/approvals/forms.py) |
| D-03 | TC-NEG-16 | Low | Task-detail comment textareas have no `maxlength`. `ApprovalTask.comment` and `ApprovalAction.comment` are both `CharField(max_length=255)`; a tester pasting >255 chars hits a DB-level error / silent truncation depending on DB strict mode. | [templates/approvals/task_detail.html](../../templates/approvals/task_detail.html) |

**Out of scope** (predicted in the plan but not actually defects):
- TC-NEG-08 (out-of-order step approval): `act_on_task` correctly re-activates the next pending task by `order` after each action; admins acting on step 2 first does not skip step 1. Verified in [apps/approvals/services.py:156-159](../../apps/approvals/services.py#L156-L159). No fix.
- TC-NEG-05 (double-click rapid submit): generic UX concern, not approvals-specific. No fix in this pass.

## Fixes

- [x] D-01 — add `clean_min_amount` / `clean_max_amount` to `ApprovalRuleForm` (reject negatives)
- [x] D-02 — add `clean()` to `ApprovalRuleForm` (reject min > max)
- [x] D-03 — add `maxlength="255"` to both comment textareas in `task_detail.html`

## Plan updates

- [x] TC-CREATE-04 — update Expected Result to the new clean form error
- [x] TC-NEG-03 — update Expected Result to the new clean form error
- [x] TC-NEG-16 — update Expected Result to client-side maxlength enforcement
