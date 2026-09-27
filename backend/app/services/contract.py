"""运维合同业务规则：状态流转、字段校验与筛选口径都收在这里。

到期判定与金额、日期的口径统一走 app.services.contract_terms，
列表、动作、统计三处共用同一份实现，不再各自计算。
"""
from __future__ import annotations

from typing import Any

from app.services.contract_terms import (
    ALGORITHM_NOTE,
    TERMINAL_STATUS,
    assess_contract,
    format_amount,
    parse_amount,
    parse_date,
)
from app.store import store

MODULE = "contract"
REQUIRED_FIELDS = ["合同编号", "服务单位", "合同金额"]
OPTIONAL_FIELDS = ["服务期限", "考核方式", "签订人员", "到期日期"]
DATE_FIELDS = ["服务期限", "到期日期"]
STATUS_ORDER = ["待签订", "履行中", "已到期", "已终止"]
ACTION_RULES = {"确认签订": "履行中", "标记到期": "已到期", "终止合同": "已终止"}
NEGATIVE_ACTIONS = []


def enrich_entry(row: dict[str, Any]) -> dict[str, Any]:
    """列表与详情共用的展示口径：状态、金额、到期说明都来自同一份算法。

    返回的是副本，不改仓库里的原始数据，已终止的合同也照常读出。
    """
    assessed = assess_contract(row)
    enriched = dict(row)
    enriched["合同状态"] = assessed["display_status"]
    enriched["到期说明"] = assessed["note"]
    if assessed["expiry"] is not None:
        enriched["到期日期"] = assessed["expiry"].isoformat()
    start = parse_date(row.get("服务期限"))
    if start is not None:
        enriched["服务期限"] = start.isoformat()
    amount_text = format_amount(row.get("合同金额"))
    if amount_text:
        enriched["合同金额"] = amount_text
    if assessed["abnormal"]:
        enriched["abnormal"] = True
    return enriched


class ContractService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("合同编号", ""))]
        enriched = [enrich_entry(row) for row in rows]
        if status:
            # 状态筛选按展示口径过滤，看到什么状态就能按什么状态筛
            enriched = [row for row in enriched if row["合同状态"] == status]
        total = len(enriched)
        start = max(page - 1, 0) * size
        return enriched[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return enrich_entry(row)

    def stats(self) -> dict[str, Any]:
        """统计卡：与列表走同一份到期判定和金额口径，保证两边对得上。"""
        assessed = [assess_contract(row) for row in store.rows(MODULE)]
        total_amount = sum(item["amount"] for item in assessed if item["amount"] is not None)
        cards = [
            {"label": "履行中合同", "value": sum(1 for item in assessed if item["display_status"] == "履行中")},
            {"label": "即将到期合同", "value": sum(1 for item in assessed if item["expiring_soon"])},
            {"label": "已超期合同", "value": sum(1 for item in assessed if item["overdue"])},
            {"label": "合同总金额", "value": format_amount(total_amount)},
        ]
        return {"cards": cards, "algorithm": ALGORITHM_NOTE}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        problems: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            problems.append(f"缺少必填字段：{'、'.join(missing)}")
        amount = parse_amount(values.get("合同金额"))
        if not missing and amount is None:
            problems.append("合同金额无法识别，请按万元填写（支持 12.5、12.5万、125000元 等写法）")
        if problems:
            return None, problems
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["合同编号"] = values.get("合同编号")
        entry["服务单位"] = values.get("服务单位")
        entry["合同金额"] = amount  # 统一存「万元」数值，写法差异在入口就收敛
        for field in OPTIONAL_FIELDS:
            raw = values.get(field)
            if raw is None or not str(raw).strip():
                continue
            if field in DATE_FIELDS:
                parsed = parse_date(raw)
                # 日期能认出就规范成 ISO 写法；认不出保留原样，由共用算法在展示时标注
                entry[field] = parsed.isoformat() if parsed is not None else str(raw).strip()
            else:
                entry[field] = raw
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return enrich_entry(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"运维合同 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于运维合同可执行范围"
        if entry.get("status") == TERMINAL_STATUS:
            return None, "运维合同已终止，不再执行状态流转，可正常查阅"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if action == "标记到期":
            # 标记到期与列表、统计走同一份算法，结论不一致时按算法说明拦下
            assessed = assess_contract(entry)
            if not assessed["overdue"]:
                reason = assessed["note"]
                if not reason and assessed["days_remaining"] is not None:
                    reason = f"距到期还有 {assessed['days_remaining']} 天，尚未超期"
                return None, f"按共用算法不能标记到期：{reason or '到期日期未超期'}"
            entry["status"] = target
            entry["pending"] = False
            entry["abnormal"] = False
            return enrich_entry(entry), f"运维合同已标记到期（{assessed['note']}）"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return enrich_entry(entry), f"运维合同已流转为{target}"
