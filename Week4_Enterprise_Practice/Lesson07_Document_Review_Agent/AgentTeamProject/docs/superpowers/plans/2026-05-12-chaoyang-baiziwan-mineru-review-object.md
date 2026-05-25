# 朝阳百子湾 MinerU 审查对象 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `朝阳区百子湾职工住宅项目.json` 成为可上传、可解析、可生成审查 session、可进入真实 RAG 试审的审查对象。

**Architecture:** 把 MinerU JSON 作为一等输入类型接入现有上传和 water-review pipeline。显式传入的 `file_path=.json` 必须优先于默认北航样例；上传后仍创建 `Contract + ReviewSession`，pipeline 产物写入 `storage/contracts/<contract_id>/water_review`，现有审查主题、审查项、真实召回试审继续按 session artifact 工作。

**Tech Stack:** FastAPI, SQLAlchemy, React/Vite, pytest, MinerU JSON, existing water_review pipeline, Chroma/RAG, LangExtract artifacts.

---

## Scope

本计划不覆盖旧 session `6f6410c8-e09d-439f-9ea8-fd73bd9e8049`。该 session 是旧审查对象，直接覆盖会破坏审计边界。实现完成后应通过上传或脚本创建一个新的 `contract_id/session_id`，再打开 `/contracts/<new_session_id>/review`。

## File Structure

- Modify: `backend/app/services/water_review_service.py`
  - 负责显式 MinerU JSON 解析优先级。
- Modify: `backend/app/services/upload_service.py`
  - 负责接受 `.json` 上传、校验 MinerU JSON、创建合同和 session。
- Modify: `backend/app/models/contract.py`
  - 让 `FileType` 明确包含 `json`。
- Modify: `frontend/src/app/pages/ContractUploadPage.tsx`
  - 让上传页允许选择 `.json`，并更新格式提示。
- Test: `backend/tests/test_water_review_mineru_json.py`
  - 覆盖显式 JSON 优先于默认样例。
- Test: `backend/tests/test_upload_mineru_json.py`
  - 覆盖上传 MinerU JSON 生成 contract/session。

---

### Task 1: Make explicit MinerU JSON win in parsing

**Files:**
- Create: `backend/tests/test_water_review_mineru_json.py`
- Modify: `backend/app/services/water_review_service.py:217-235`

- [ ] **Step 1: Write failing parser test**

Create `backend/tests/test_water_review_mineru_json.py`:

```python
import json
from pathlib import Path

from app.services import water_review_service


def _mineru_doc(text: str) -> dict:
    return {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "bbox": [10, 20, 120, 40],
                        "type": "title",
                        "index": 1,
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "content": text,
                                        "type": "text",
                                        "bbox": [10, 20, 120, 40],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_parse_document_uses_explicit_mineru_json_before_default(tmp_path, monkeypatch):
    default_json = tmp_path / "default.json"
    explicit_json = tmp_path / "朝阳区百子湾职工住宅项目.json"
    default_json.write_text(json.dumps(_mineru_doc("北航默认样例")), encoding="utf-8")
    explicit_json.write_text(json.dumps(_mineru_doc("朝阳区百子湾职工住宅项目")), encoding="utf-8")
    monkeypatch.setattr(water_review_service, "DEFAULT_MINERU_JSON", default_json)
    monkeypatch.setattr(water_review_service, "DEFAULT_MINERU_MD", tmp_path / "missing.md")

    blocks = water_review_service.parse_document(str(explicit_json))

    assert [block.text for block in blocks] == ["朝阳区百子湾职工住宅项目"]
    assert blocks[0].page == 1
    assert blocks[0].bbox == [10.0, 20.0, 120.0, 40.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
uv run pytest tests/test_water_review_mineru_json.py -q
```

Expected before implementation:

```text
FAILED ... assert ['北航默认样例'] == ['朝阳区百子湾职工住宅项目']
```

- [ ] **Step 3: Implement explicit file routing**

In `backend/app/services/water_review_service.py`, replace `parse_document()` with:

```python
def parse_document(file_path: str | None = None) -> list[ParsedBlock]:
    """Load an explicit source first, then fall back to bundled MinerU samples."""
    if file_path:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".json" and path.exists():
            return _parse_mineru_json(path)
        if suffix == ".md" and path.exists():
            return _parse_markdown(path)
        if suffix == ".pdf":
            return _parse_pdf(str(path))
        if suffix == ".docx":
            return _parse_docx(str(path))
        return []

    if DEFAULT_MINERU_JSON.exists():
        return _parse_mineru_json(DEFAULT_MINERU_JSON)
    if DEFAULT_MINERU_MD.exists():
        return _parse_markdown(DEFAULT_MINERU_MD)
    return []
```

- [ ] **Step 4: Run parser test**

Run:

```bash
cd backend
uv run pytest tests/test_water_review_mineru_json.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Smoke parse the real file**

Run:

```bash
cd backend
uv run python - <<'PY'
from app.services.water_review_service import parse_document, build_chunks
path = "data/朝阳区百子湾职工住宅项目.json"
blocks = parse_document(path)
chunks = build_chunks(blocks)
print({"blocks": len(blocks), "chunks": len(chunks), "first": blocks[0].text if blocks else ""})
PY
```

Expected:

```text
{'blocks': <positive>, 'chunks': <positive>, 'first': '朝阳区百子湾职工住宅项目'}
```

---

### Task 2: Accept MinerU JSON uploads

**Files:**
- Create: `backend/tests/test_upload_mineru_json.py`
- Modify: `backend/app/models/contract.py:9-12`
- Modify: `backend/app/services/upload_service.py:18-120`

- [ ] **Step 1: Write failing upload test**

Create `backend/tests/test_upload_mineru_json.py`:

```python
import asyncio
import io
import json

import pytest
from fastapi import UploadFile

from app.database import SessionLocal
from app.models.contract import Contract
from app.models.session import ReviewSession
from app.services import upload_service


def _mineru_bytes() -> bytes:
    return json.dumps(
        {
            "pdf_info": [
                {
                    "page_idx": 0,
                    "para_blocks": [
                        {
                            "bbox": [10, 20, 120, 40],
                            "type": "title",
                            "index": 1,
                            "lines": [{"spans": [{"content": "朝阳区百子湾职工住宅项目"}]}],
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_handle_upload_accepts_mineru_json(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service.settings, "storage_path", str(tmp_path / "storage"))

    async def noop_background_ocr(session_id: str, file_path: str, file_type: str) -> None:
        return None

    created_tasks = []
    monkeypatch.setattr(upload_service, "_background_ocr", noop_background_ocr)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: created_tasks.append(coro))

    upload = UploadFile(filename="朝阳区百子湾职工住宅项目.json", file=io.BytesIO(_mineru_bytes()))
    db = SessionLocal()
    try:
        response = await upload_service.handle_upload(upload, db, user_id="tester")
        contract = db.query(Contract).filter(Contract.id == response.contract_id).first()
        session = db.query(ReviewSession).filter(ReviewSession.id == response.session_id).first()
    finally:
        for coro in created_tasks:
            coro.close()
        db.close()

    assert response.file_type == "json"
    assert response.title == "朝阳区百子湾职工住宅项目"
    assert contract is not None
    assert contract.file_type == "json"
    assert contract.file_path.endswith("original.json")
    assert session is not None
    assert session.state == "parsing"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
uv run pytest tests/test_upload_mineru_json.py -q
```

Expected before implementation:

```text
FAILED ... unsupported file type
```

- [ ] **Step 3: Add `json` file type**

In `backend/app/models/contract.py`:

```python
class FileType(str, enum.Enum):
    pdf = "pdf"
    docx = "docx"
    json = "json"
```

- [ ] **Step 4: Add JSON detection and integrity check**

In `backend/app/services/upload_service.py`, update detection:

```python
def _detect_file_type(header: bytes) -> str | None:
    if header[:5] == PDF_MAGIC:
        return "pdf"
    if header[:4] == ZIP_MAGIC:
        return "docx"
    if header.lstrip().startswith((b"{", b"[")):
        return "json"
    return None
```

Add:

```python
def _check_mineru_json_integrity(file_path: str) -> bool:
    try:
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    pages = data.get("pdf_info")
    if not isinstance(pages, list) or not pages:
        return False
    return any(isinstance(page, dict) and page.get("para_blocks") for page in pages)
```

Update filename handling:

```python
original_filename = file.filename or f"contract.{file_type}"
safe_filename = f"original.{file_type}"
file_path = str(storage_dir / safe_filename)
```

Update integrity branch:

```python
elif file_type == "docx":
    if not _check_docx_integrity(file_path):
        shutil.rmtree(storage_dir, ignore_errors=True)
        raise APIError.corrupt_file()
elif file_type == "json":
    if not _check_mineru_json_integrity(file_path):
        shutil.rmtree(storage_dir, ignore_errors=True)
        raise APIError.corrupt_file()
```

- [ ] **Step 5: Run upload test**

Run:

```bash
cd backend
uv run pytest tests/test_upload_mineru_json.py -q
```

Expected:

```text
1 passed
```

---

### Task 3: Let upload page select JSON

**Files:**
- Modify: `frontend/src/app/pages/ContractUploadPage.tsx:24-36`
- Modify: `frontend/src/app/pages/ContractUploadPage.tsx:130-135`
- Modify: `frontend/src/app/pages/ContractUploadPage.tsx:227`

- [ ] **Step 1: Update frontend validation**

In `frontend/src/app/pages/ContractUploadPage.tsx`, change the extension check:

```tsx
if (!['pdf', 'docx', 'json'].includes(ext)) {
  errs.push(`文件格式不支持，仅允许 PDF / DOCX / MinerU JSON（当前：${ext}）`);
}
```

- [ ] **Step 2: Update file picker and copy**

Change visible copy:

```tsx
<p className="text-xs text-gray-400 mt-1.5">支持格式：PDF / DOCX / MinerU JSON · 最大 50MB</p>
```

Change input accept:

```tsx
accept=".pdf,.docx,.json"
```

Change API note:

```tsx
POST /contracts/upload (multipart/form-data) · 文件大小上限 50MB · 格式：PDF/DOCX/MinerU JSON
```

- [ ] **Step 3: Build frontend**

Run:

```bash
cd frontend
npm run build
```

Expected:

```text
✓ built
```

The existing Vite dynamic/static import warning in `contracts.ts` is acceptable.

---

### Task 4: Verify the real Baiziwan document end-to-end

**Files:**
- No code files unless prior tasks fail.

- [ ] **Step 1: Run backend targeted tests**

Run:

```bash
cd backend
uv run pytest \
  tests/test_water_review_mineru_json.py \
  tests/test_upload_mineru_json.py \
  tests/test_review_config_service.py \
  tests/test_review_config_integration.py \
  -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 2: Upload the existing local JSON through API**

Run:

```bash
cd backend
curl -sS -X POST http://127.0.0.1:8000/api/v1/contracts/upload \
  -H 'X-User-ID: tester' \
  -F 'file=@data/朝阳区百子湾职工住宅项目.json;type=application/json' \
  | jq '{contract_id, session_id, title, file_type, state}'
```

Expected:

```json
{
  "contract_id": "...",
  "session_id": "...",
  "title": "朝阳区百子湾职工住宅项目",
  "file_type": "json",
  "state": "parsing"
}
```

- [ ] **Step 3: Confirm artifact generation**

Use the returned `contract_id` and `session_id`:

```bash
cd backend
uv run python scripts/backfill_water_rag_session.py <session_id> \
  --file-path "storage/contracts/<contract_id>/original.json" \
  --artifact-dir "storage/contracts/<contract_id>/water_review"
```

Expected:

```text
[water-rag] pipeline complete: fields=<n>, facts=<n>, findings=<n>, items=<n>
[water-rag] database commit complete
```

Then verify:

```bash
test -s "storage/contracts/<contract_id>/water_review/review_chunks.json"
test -s "storage/contracts/<contract_id>/water_review/issues.json"
test -s "storage/contracts/<contract_id>/water_review/review_rule_topics.json"
```

- [ ] **Step 4: Open new review page**

Open:

```text
http://127.0.0.1:5173/contracts/<session_id>/review
```

Expected:

- 页面展示朝阳百子湾项目对应的问题列表。
- 审查主题仍显示 SCMC 主题列表。
- 点击“新增审查项”后可用当前简报试审。
- preview 面板显示 `RAG Agent`、chunk 页码、召回文本、LLM 结论。

- [ ] **Step 5: Confirm preview uses Baiziwan chunks**

Run a preview with a Baiziwan-specific phrase:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/review-config/check-items/preview \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON' | jq '{source: .evidence_bundle.source, persisted: .agent_trace.persisted, query_has_baiziwan: (.agent_trace.query | contains("百子湾")), evidence_count: (.evidence_bundle.retrieval_matches | length), first_text: .evidence_bundle.retrieval_matches[0].text}'
{
  "session_id": "<session_id>",
  "topic_id": "scmc-001",
  "executor_type_id": "manual_basic",
  "review_type": "人工基础核验",
  "expert_brief": {
    "item_name": "百子湾项目总投资核验",
    "review_objective": "核查朝阳区百子湾职工住宅项目总投资是否前后一致。",
    "evidence_instruction": "优先查看项目概况、投资估算表和附件。",
    "judgement_basis": "按水影响评价和水土保持审查口径判断金额、单位、来源是否一致。",
    "pass_condition": "总投资金额、单位和来源明确且章节表格一致。",
    "issue_condition": "未说明总投资；金额单位不一致；章节与表格不一致",
    "regulation_text": "项目总投资应在报告正文、表格和附件之间保持一致。"
  }
}
JSON
```

Expected:

```json
{
  "source": "rag_agent",
  "persisted": false,
  "query_has_baiziwan": true,
  "evidence_count": 1
}
```

`first_text` 应包含朝阳百子湾项目文本，而不是北航沙河图书馆文本。

---

## Self-Review

**Spec coverage:** 覆盖了新 MinerU JSON 作为审查对象、上传入口、显式解析优先级、session artifact 生成、前端打开新 review 页、真实召回试审验证。

**Placeholder scan:** 无 `TBD/TODO/implement later`。每个代码任务给出具体文件和代码片段。

**Type consistency:** `file_type=json` 从上传检测、Contract 枚举、前端 accept 到 pipeline `parse_document(.json)` 一致；不需要数据库迁移，因为 `Contract.file_type` 是 `String(10)`。

**Risk:** 后台上传会自动触发 pipeline，手动 backfill 可能重复生成问题。执行验收时优先等后台完成；只有后台失败或需要确定性重跑时再执行 Task 4 Step 3。
