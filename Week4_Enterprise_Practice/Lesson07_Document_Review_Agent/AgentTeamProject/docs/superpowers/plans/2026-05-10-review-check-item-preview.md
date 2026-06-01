# Review Check Item Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an expert-facing rule workbench where a review expert can edit a draft check item, immediately run a preview review against the current session, inspect evidence and precheck output, then save the rule under the current SCMC topic.

**Architecture:** Add a non-persistent preview endpoint under review config. The backend normalizes the draft check item, builds an evidence bundle from current session review items and water-review artifacts when available, runs the configured executor precheck, and returns evidence, facts, conclusion, and rule-improvement suggestions. The frontend turns the existing check-item modal into a rule debugger with editable rule fields on the left and preview results on the right.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React, TypeScript, Vite, existing review config and HITL review APIs.

---

### Task 1: Backend Draft Preview API

**Files:**
- Modify: `backend/app/api/review_config.py`
- Modify: `backend/app/services/review_config_service.py`
- Test: `backend/tests/test_review_config_integration.py`

- [x] **Step 1: Write API integration test**

Add a test that posts an unsaved draft to `/api/v1/review-config/check-items/preview` with `session_id`, `topic_id`, `executor_type_id`, `review_sub_type`, `evidence_scope`, `target_fields`, `review_criteria`, `expected_result`, and `failure_conditions`. Expected response:

```python
assert response.status_code == 200
payload = response.json()
assert payload["check_item"]["review_sub_type"] == "乔灌草配置完整性"
assert payload["precheck_result"]["executor_type_id"] == "evidence_presence"
assert payload["evidence_bundle"]["evidence_texts"]
assert payload["review_conclusion"]["status"] in {"pass", "needs_review", "potential_issue", "pending"}
assert payload["suggested_rule_improvements"]
```

- [x] **Step 2: Implement service function**

Add `preview_check_item_spec(session_id: str, data: dict[str, Any], db: Session) -> dict[str, Any]` to `review_config_service.py`. It should:

```python
normalized = _normalize_check_item({**data, "id": data.get("id") or "draft-preview"}, load_review_config()["executor_types"])
evidence_bundle = _build_preview_evidence_bundle(session_id, normalized, db)
precheck = execute_check_item_precheck(normalized, evidence_bundle)
return {
    "check_item": normalized,
    "evidence_bundle": evidence_bundle,
    "precheck_result": precheck,
    "review_conclusion": _preview_conclusion(normalized, evidence_bundle, precheck),
    "suggested_rule_improvements": _preview_rule_improvements(normalized, evidence_bundle, precheck),
}
```

The first version must not save the draft and must not call the LLM. It should provide deterministic preview results quickly from current session data.

- [x] **Step 3: Build evidence bundle from session data**

Implement `_build_preview_evidence_bundle` using `ReviewItem` rows for the session. It should collect matching rows by target fields, review criteria, expected result, failure conditions, rule id, and topic-related text. Return:

```python
{
    "evidence_texts": [...],
    "evidence_locations": [{"page_number": 3, "paragraph_index": 2, "highlight_anchor": "chunk-task5-plant"}],
    "matched_target_fields": [...],
    "missing_target_fields": [...],
    "structured_facts": [...],
    "cross_reference_findings": [...],
    "source": "session_review_items",
}
```

Parse `ai_reasoning` JSON from matching ReviewItem rows to reuse `structured_facts`, `cross_chapter_findings`, and `langextract_grounding` when present.

- [x] **Step 4: Add route**

Add:

```python
class PreviewCheckItemPayload(CheckItemPayload):
    session_id: str

@router.post("/check-items/preview")
def preview_check_item(payload: PreviewCheckItemPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    ...
```

Return 404 if `session_id` does not exist, 400 for invalid topic/executor config.

- [x] **Step 5: Run backend tests**

Run:

```bash
cd backend
uv run pytest tests/test_review_config_integration.py tests/test_review_config_service.py tests/test_review_executor_service.py -q
```

Expected: all selected tests pass.

### Task 2: Frontend Preview Client And Rule Debugger UI

**Files:**
- Modify: `frontend/src/app/api/reviewConfig.ts`
- Modify: `frontend/src/app/pages/HITLReviewPage.tsx`

- [x] **Step 1: Add TypeScript API types**

Add `PreviewCheckItemPayload`, `PreviewCheckItemResponse`, and:

```ts
export function previewCheckItem(body: PreviewCheckItemPayload): Promise<PreviewCheckItemResponse> {
  return apiClient.post<PreviewCheckItemResponse>('/review-config/check-items/preview', body);
}
```

- [x] **Step 2: Add preview state**

In `HITLReviewPage`, add:

```ts
const [previewResult, setPreviewResult] = useState<PreviewCheckItemResponse | null>(null);
const [isPreviewing, setIsPreviewing] = useState(false);
```

Reset `previewResult` when opening a new draft or cancelling.

- [x] **Step 3: Add run-preview handler**

Add `previewCheckItemDraft`. It should build the same payload as save, include `session_id`, call `previewCheckItem`, and update `previewResult`. It must not save the draft.

- [x] **Step 4: Turn modal into rule debugger**

Keep the modal overlay. Change its body to a two-column desktop layout:

```text
left: editable rule fields
right: preview result panel
```

The footer buttons should be `试审当前规则`, `保存规则`, and `取消`. Disable preview while loading or if no `review_sub_type`.

- [x] **Step 5: Render preview result**

Show:

```text
审查结论状态
结论摘要
命中字段 / 缺失字段
召回证据文本与位置
结构化事实
规则改进建议
预检查明细
```

If there is no preview yet, show a quiet empty state: `编辑规则后点击“试审当前规则”验证效果。`

- [x] **Step 6: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: build passes.

### Task 3: End-To-End Verification

**Files:**
- No new source files unless fixing issues found by verification.

- [x] **Step 1: Run targeted backend tests**

Run:

```bash
cd backend
uv run pytest tests/test_review_config_integration.py tests/test_review_config_service.py tests/test_review_executor_service.py -q
```

- [x] **Step 2: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

- [x] **Step 3: Browser verification**

Use the current in-app browser URL. Verify:

```text
1. 点击新增打开弹层。
2. 弹层内能看到“试审当前规则”。
3. 点击试审后右侧出现结论、证据、字段命中/缺失和规则改进建议。
4. 不保存时关闭弹层不会新增审查项。
5. 点击保存规则后审查项出现在当前主题下。
```

### Self-Review

- Spec coverage: Covers expert editable rule content, immediate service preview, evidence feedback, save-after-validation workflow.
- Placeholder scan: No TBD/TODO placeholders are left.
- Type consistency: Backend preview response maps to frontend `PreviewCheckItemResponse`; save payload remains compatible with existing `CheckItemPayload`.
