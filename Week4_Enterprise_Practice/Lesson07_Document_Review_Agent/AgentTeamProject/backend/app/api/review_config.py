from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.database import get_db
from app.models.session import ReviewSession
from app.services import review_agent_service, review_config_service


router = APIRouter()


class ExecutorTypePayload(BaseModel):
    id: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = True


class CheckItemPayload(BaseModel):
    id: Optional[str] = None
    topic_id: Optional[str] = None
    rule_id: Optional[str] = None
    executor_type_id: Optional[str] = None
    review_type: Optional[str] = None
    review_sub_type: Optional[str] = None
    status: Optional[str] = "pending"
    conclusion: Optional[str] = None
    evidence_scope: Optional[dict[str, Any]] = Field(default_factory=dict)
    target_fields: Optional[list[str]] = Field(default_factory=list)
    regulation_clauses: Optional[list[str]] = Field(default_factory=list)
    review_criteria: Optional[str] = None
    expected_result: Optional[str] = None
    failure_conditions: Optional[list[str]] = Field(default_factory=list)
    source_rule_snapshot: Optional[dict[str, Any]] = Field(default_factory=dict)
    expert_brief: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = True


class PreviewCheckItemPayload(CheckItemPayload):
    session_id: str


@router.get("")
def get_review_config() -> dict[str, Any]:
    try:
        return review_config_service.load_review_config()
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc


@router.get("/executor-types")
def list_executor_types() -> dict[str, Any]:
    try:
        return {"items": review_config_service.list_executor_types()}
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc


@router.post("/executor-types")
def create_executor_type(payload: ExecutorTypePayload) -> dict[str, Any]:
    try:
        item = review_config_service.create_executor_type(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc
    return item


@router.patch("/executor-types/{executor_id}")
def update_executor_type(executor_id: str, payload: ExecutorTypePayload) -> dict[str, Any]:
    try:
        return review_config_service.update_executor_type(executor_id, payload.model_dump(exclude_unset=True, exclude_none=True))
    except KeyError as exc:
        raise APIError.not_found("ExecutorType") from exc
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc


@router.delete("/executor-types/{executor_id}")
def delete_executor_type(executor_id: str) -> dict[str, Any]:
    try:
        review_config_service.delete_executor_type(executor_id)
    except KeyError as exc:
        raise APIError.not_found("ExecutorType") from exc
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc
    return {"id": executor_id, "deleted": True}


@router.get("/check-items")
def list_check_items(topic_id: Optional[str] = Query(default=None)) -> dict[str, Any]:
    try:
        return {"items": review_config_service.list_check_item_specs(topic_id)}
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc


@router.post("/check-items")
def create_check_item(payload: CheckItemPayload) -> dict[str, Any]:
    try:
        item = review_config_service.create_check_item_spec(payload.model_dump(exclude_unset=True, exclude_none=True))
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc
    return item


@router.post("/check-items/preview")
def preview_check_item(payload: PreviewCheckItemPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.query(ReviewSession).filter(ReviewSession.id == payload.session_id).first()
    if not session:
        raise APIError.not_found("ReviewSession")
    try:
        return review_config_service.preview_check_item_spec(
            payload.session_id,
            payload.model_dump(exclude_unset=True, exclude_none=True, exclude={"session_id"}),
            db,
        )
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc
    except review_agent_service.ReviewAgentUnavailable as exc:
        raise APIError.service_unavailable(str(exc)) from exc


@router.patch("/check-items/{item_id}")
def update_check_item(item_id: str, payload: CheckItemPayload) -> dict[str, Any]:
    try:
        return review_config_service.update_check_item_spec(item_id, payload.model_dump(exclude_unset=True, exclude_none=True))
    except KeyError as exc:
        raise APIError.not_found("ReviewCheckItem") from exc
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc


@router.delete("/check-items/{item_id}")
def delete_check_item(item_id: str) -> dict[str, Any]:
    try:
        review_config_service.delete_check_item_spec(item_id)
    except KeyError as exc:
        raise APIError.not_found("ReviewCheckItem") from exc
    except ValueError as exc:
        raise APIError.bad_request(str(exc)) from exc
    return {"id": item_id, "deleted": True}
