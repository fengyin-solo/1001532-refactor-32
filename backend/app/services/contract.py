"""运维合同业务规则：列表展示、动作流转、统计卡片统一走 contract_rules。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

from .contract_rules import (
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_TERMINATED,
    expiry_view,
    format_amount,
    parse_amount,
    parse_date,
)

MODULE = "contract"
REQUIRED_FIELDS = ["合同编号", "服务单位", "合同金额"]
WRITABLE_FIELDS = ["合同编号", "服务单位", "合同金额", "服务期限", "考核方式", "签订人员", "到期日期"]
STATUS_ORDER = [STATUS_PENDING, STATUS_ACTIVE, STATUS_EXPIRED, STATUS_TERMINATED]
ACTION_RULES = {"确认签订": STATUS_ACTIVE, "标记到期": STATUS_EXPIRED, "终止合同": STATUS_TERMINATED}


class ContractService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        today: date | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("合同编号", ""))]
        # 状态过滤以 contract_rules 的到期口径为准，保证列表与统计卡一致
        presented = [self.present_entry(row, today=today) for row in rows]
        if status:
            presented = [row for row in presented if row["status"] == status]
        total = len(presented)
        start = max(page - 1, 0) * size
        return presented[start:start + size], total

    def get_entry(self, entry_id: int, *, today: date | None = None) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self.present_entry(entry, today=today)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        problems = list(missing)
        if "合同金额" not in missing and parse_amount(values.get("合同金额")) is None:
            problems.append(f"合同金额「{values.get('合同金额')}」无法识别为金额")
        if problems:
            return None, problems
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in WRITABLE_FIELDS:
            if str(values.get(field) or "").strip():
                entry[field] = values[field]
        amount = parse_amount(entry.get("合同金额"))
        if amount is not None:
            entry["合同金额"] = float(amount)
        expiry = parse_date(entry.get("到期日期"))
        if expiry is not None:
            entry["到期日期"] = expiry.isoformat()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self, entry_id: int, action: str, *, today: date | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"运维合同 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于运维合同可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        current = expiry_view(entry, today=today)["status"]
        # 已终止是终态：保留原状态，照旧可读，不再参与动作与到期判断
        if current == STATUS_TERMINATED:
            return None, "运维合同已终止，终止合同只读，不能再执行动作"
        if action == "确认签订" and current != STATUS_PENDING:
            return None, f"当前状态为「{current}」，只有待签订的合同可以确认签订"
        if action == "标记到期":
            if current == STATUS_EXPIRED:
                return None, "运维合同已到期，无需重复标记"
            if current != STATUS_ACTIVE:
                return None, f"当前状态为「{current}」，只有履行中的合同可以标记到期"
            expiry = parse_date(entry.get("到期日期"))
            if expiry is None:
                return None, "到期日期缺失或无法识别，请先补录有效的到期日期再标记到期"

        entry["status"] = target
        entry["pending"] = target != STATUS_TERMINATED
        # abnormal 是与到期无关的遗留标记，动作只改状态，不顺手改动它
        return self.present_entry(entry, today=today), f"运维合同已{action}"

    def stats(self, *, today: date | None = None) -> dict[str, Any]:
        """统计卡口径：与列表、动作共用 expiry_view，逐行只算一次。"""
        presented = [self.present_entry(row, today=today) for row in store.rows(MODULE)]
        counts = {status: 0 for status in STATUS_ORDER}
        total_amount = parse_amount(0)
        assert total_amount is not None
        for row in presented:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            amount = parse_amount(row.get("合同金额"))
            if amount is not None:
                total_amount += amount
        return {
            "status_counts": counts,
            "active_count": counts.get(STATUS_ACTIVE, 0),
            "expiring_count": sum(1 for row in presented if row["expiring"]),
            "overdue_count": sum(1 for row in presented if row["overdue"]),
            "total_amount": format_amount(total_amount),
        }

    def present_entry(self, entry: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
        """按共用口径生成对外视图：生效状态、超期/即将到期标记、金额展示。"""
        view = expiry_view(entry, today=today)
        presented = dict(entry)
        presented.update(view)
        presented["合同状态"] = view["status"]
        presented["status"] = view["status"]
        presented["合同金额"] = format_amount(entry.get("合同金额"))
        return presented
