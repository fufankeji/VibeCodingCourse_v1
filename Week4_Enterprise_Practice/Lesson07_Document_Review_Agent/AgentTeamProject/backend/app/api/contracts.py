from typing import Optional

from fastapi import APIRouter, Depends, Header, UploadFile, File, Form, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.database import get_db
from app.models.contract import Contract
from app.models.session import ReviewSession
from app.schemas.contract import ContractListResponse, ContractResponse, UploadResponse
from app.services import upload_service
from app.services.contract_entry_service import build_contract_entry

router = APIRouter()


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_contract(
    file: UploadFile = File(...),
    contract_title: str | None = Form(default=None),
    x_user_id: str = Header(default="anonymous", alias="X-User-ID"),
    db: Session = Depends(get_db),
):
    return await upload_service.handle_upload(file, db, user_id=x_user_id, contract_title=contract_title)


@router.get("", response_model=ContractListResponse)
def list_contracts(
    cursor: Optional[str] = Query(default=None, description="游标分页，传入上一页最后一条 contract id"),
    limit: int = Query(default=20, ge=1, le=100),
    state: Optional[str] = Query(default=None, description="按 session state 筛选"),
    db: Session = Depends(get_db),
):
    latest_session_subq = (
        db.query(
            ReviewSession.contract_id.label("contract_id"),
            func.max(ReviewSession.created_at).label("latest_created_at"),
        )
        .group_by(ReviewSession.contract_id)
        .subquery()
    )
    latest_session_join = and_(
        ReviewSession.contract_id == Contract.id,
        ReviewSession.created_at == latest_session_subq.c.latest_created_at,
    )

    if state:
        query = (
            db.query(Contract)
            .join(latest_session_subq, latest_session_subq.c.contract_id == Contract.id)
            .join(ReviewSession, latest_session_join)
            .filter(ReviewSession.state == state)
            .order_by(Contract.created_at.desc())
        )
    else:
        query = db.query(Contract).order_by(Contract.created_at.desc())

    if cursor:
        anchor = db.query(Contract).filter(Contract.id == cursor).first()
        if anchor:
            query = query.filter(Contract.created_at < anchor.created_at)

    # Count total before pagination
    total = query.count()

    items = query.limit(limit + 1).all()
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]

    next_cursor = items[-1].id if has_more and items else None

    # Join session info for each contract
    result_items = []
    for c in items:
        resp = ContractResponse.model_validate(c)
        session = db.query(ReviewSession).filter(ReviewSession.contract_id == c.id).order_by(ReviewSession.created_at.desc()).first()
        if session:
            resp.session_id = session.id
            resp.session_state = session.state
        _apply_contract_entry(resp, build_contract_entry(db, c, session))
        result_items.append(resp)

    return ContractListResponse(
        items=result_items,
        total=total,
        next_cursor=next_cursor,
    )


@router.get("/{contract_id}", response_model=ContractResponse)
def get_contract(contract_id: str, db: Session = Depends(get_db)):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise APIError.not_found("Contract")
    resp = ContractResponse.model_validate(contract)
    session = db.query(ReviewSession).filter(ReviewSession.contract_id == contract_id).order_by(ReviewSession.created_at.desc()).first()
    if session:
        resp.session_id = session.id
        resp.session_state = session.state
    _apply_contract_entry(resp, build_contract_entry(db, contract, session))
    return resp


def _apply_contract_entry(resp: ContractResponse, entry: dict) -> None:
    for key, value in entry.items():
        setattr(resp, key, value)
