from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ContractBase(BaseModel):
    title: str
    original_filename: str
    file_type: str


class ContractCreate(ContractBase):
    uploaded_by: str = "anonymous"


class ContractResponse(BaseModel):
    id: str
    title: str
    original_filename: str
    file_type: str
    contract_status: str
    is_scanned_document: bool
    file_path: str
    uploaded_by: str
    uploaded_at: datetime
    created_at: datetime
    updated_at: datetime
    session_id: Optional[str] = None
    session_state: Optional[str] = None
    latest_parse_job_status: Optional[str] = None
    latest_parse_job_stage: Optional[str] = None
    latest_parse_job_error_code: Optional[str] = None
    latest_parse_job_error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 0
    can_retry_parse: bool = False
    retry_block_reason: Optional[str] = None
    can_view_result: bool = False
    entry_route_type: Optional[str] = None
    entry_action_label: str = "不可进入"
    read_only: bool = False

    model_config = {"from_attributes": True}


class ContractListResponse(BaseModel):
    items: list[ContractResponse]
    total: int
    next_cursor: Optional[str] = None


class UploadResponse(BaseModel):
    contract_id: str
    session_id: str
    title: str
    file_type: str
    is_scanned_document: bool
    state: str
    message: str
