"""运维合同接口：维护运维合同，覆盖确认签订、标记到期、终止合同等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.contract import ContractService

router = APIRouter(prefix="/api/contract", tags=["运维合同"])

service = ContractService()

LIST_FIELDS = ["合同编号", "服务单位", "合同金额", "服务期限", "考核方式", "签订人员", "到期日期", "合同状态"]
STATUSES = ["待签订", "履行中", "已到期", "已终止"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按合同编号检索"),
    status: str | None = Query(default=None, description="待签订、履行中、已到期、已终止"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按合同编号与状态过滤运维合同列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats", response_model=dict)
def contract_stats() -> dict[str, Any]:
    """统计卡：履行中、即将到期、超期条数与合同总金额，口径与列表完全一致。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出运维合同清单：返回当前口径下的全量数据（含生效状态与金额格式）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "contract", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条运维合同明细；已终止合同照常可读，不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"运维合同 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条运维合同，缺字段或金额无法识别时说明原因而不是静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="运维合同已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条运维合同执行确认签订、标记到期、终止合同；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
