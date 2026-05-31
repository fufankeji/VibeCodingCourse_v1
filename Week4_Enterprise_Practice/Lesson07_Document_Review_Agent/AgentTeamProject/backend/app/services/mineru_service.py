"""MinerU Open API integration for uploaded review documents."""

from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import settings


class MinerUAPIError(RuntimeError):
    """Raised when MinerU parsing cannot produce a usable artifact."""


@dataclass
class MinerUParseArtifacts:
    json_path: Path | None = None
    markdown_path: Path | None = None
    zip_path: Path | None = None
    batch_id: str = ""
    task_id: str = ""
    zip_url: str = ""

    @property
    def best_parse_path(self) -> Path | None:
        return self.json_path or self.markdown_path


def parse_file_to_artifacts(file_path: str, output_dir: Path) -> MinerUParseArtifacts:
    token = _auth_token()
    if not token:
        raise MinerUAPIError("MINERU_TOKEN or MINERU_ACCESS_KEY is required")

    source = Path(file_path)
    if not source.exists():
        raise MinerUAPIError(f"Source file not found: {source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = settings.mineru_base_url.rstrip("/")
    headers = _headers(token)
    with httpx.Client(timeout=settings.mineru_request_timeout) as client:
        batch_id = _submit_local_file(client, base_url, headers, source)
        task = _wait_batch_result(client, base_url, headers, batch_id)
        zip_url = str(task.get("full_zip_url") or "").strip()
        if not zip_url:
            raise MinerUAPIError("MinerU result did not include full_zip_url")
        response = client.get(zip_url, headers=headers)
        response.raise_for_status()

    artifacts = extract_zip_artifacts(response.content, output_dir)
    artifacts.batch_id = batch_id
    artifacts.task_id = str(task.get("task_id") or "")
    artifacts.zip_url = zip_url
    if artifacts.best_parse_path is None:
        raise MinerUAPIError("MinerU zip did not contain usable Markdown or structured JSON")
    return artifacts


def extract_zip_artifacts(zip_bytes: bytes, output_dir: Path) -> MinerUParseArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "mineru_result.zip"
    zip_path.write_bytes(zip_bytes)

    structured_json: dict[str, Any] | None = None
    markdown_text = ""
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith(".json"):
                candidate = _load_json_member(zf, name)
                if _is_structured_mineru_json(candidate):
                    structured_json = candidate
            elif lower.endswith(".md") and (not markdown_text or Path(name).name == "full.md"):
                markdown_text = zf.read(name).decode("utf-8", errors="replace")

    json_path = None
    if structured_json is not None:
        json_path = output_dir / "parsed.json"
        json_path.write_text(json.dumps(structured_json, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown_path = None
    if markdown_text.strip():
        markdown_path = output_dir / "full.md"
        markdown_path.write_text(markdown_text, encoding="utf-8")

    return MinerUParseArtifacts(json_path=json_path, markdown_path=markdown_path, zip_path=zip_path)


def _auth_token() -> str:
    return (settings.mineru_token or settings.mineru_access_key).strip()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }


def _submit_local_file(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    source: Path,
) -> str:
    payload = {
        "files": [{"name": source.name, "data_id": source.stem[:128]}],
        "model_version": settings.mineru_model_version,
        "enable_formula": settings.mineru_enable_formula,
        "enable_table": settings.mineru_enable_table,
        "language": settings.mineru_language,
    }
    response = client.post(f"{base_url}/file-urls/batch", headers=headers, json=payload)
    response.raise_for_status()
    body = response.json()
    _ensure_success(body)
    data = body.get("data") or {}
    batch_id = str(data.get("batch_id") or "").strip()
    upload_urls = data.get("file_urls") or []
    if not batch_id or not upload_urls:
        raise MinerUAPIError("MinerU upload-url response is missing batch_id or file_urls")

    upload_response = client.put(str(upload_urls[0]), content=source.read_bytes())
    upload_response.raise_for_status()
    return batch_id


def _wait_batch_result(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    batch_id: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + settings.mineru_poll_timeout_seconds
    interval = max(1, settings.mineru_poll_interval_seconds)
    last_state = "pending"
    while time.monotonic() < deadline:
        response = client.get(f"{base_url}/extract-results/batch/{batch_id}", headers=headers)
        response.raise_for_status()
        body = response.json()
        _ensure_success(body)
        results = _extract_results(body.get("data") or {})
        if results:
            task = results[0]
            last_state = str(task.get("state") or last_state)
            if last_state == "done":
                return task
            if last_state == "failed":
                raise MinerUAPIError(str(task.get("err_msg") or "MinerU parsing failed"))
        time.sleep(interval)
    raise MinerUAPIError(f"MinerU parsing timed out: batch_id={batch_id}, state={last_state}")


def _extract_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("extract_result") or data.get("results") or []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _ensure_success(body: dict[str, Any]) -> None:
    if body.get("code") not in (0, "0", None):
        raise MinerUAPIError(str(body.get("msg") or "MinerU API returned an error"))


def _load_json_member(zf: zipfile.ZipFile, name: str) -> Any:
    try:
        return json.loads(zf.read(name).decode("utf-8"))
    except Exception:
        return None


def _is_structured_mineru_json(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    pdf_info = candidate.get("pdf_info")
    return isinstance(pdf_info, list) and bool(pdf_info)
