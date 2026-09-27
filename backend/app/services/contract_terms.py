"""运维合同共用算法：到期判定与金额、日期口径的唯一实现。

列表、动作、统计三处都只调用这里的函数，不再各自计算，
保证超期条数、合同状态与统计卡永远对得上。
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# 距到期多少天以内算「即将到期」
EXPIRING_SOON_DAYS = 30

TERMINAL_STATUS = "已终止"
OVERDUE_STATUS = "已到期"

# 同一份算法说明：接口、统计卡与动作提示都引用这段文字，不再各写一套。
ALGORITHM_NOTE = (
    "到期判定口径："
    "1. 已终止的合同不再参与到期推算，状态固定为「已终止」，可正常查阅；"
    "2. 到期日期缺失或无法识别时，不判定超期，并在到期说明里标注；"
    "3. 到期日期早于服务期限（签订日期）视为日期异常，不判定超期，标记为异常；"
    "4. 到期日期早于今天即为超期，合同状态按「已到期」展示；"
    f"5. 到期日期距今不超过 {EXPIRING_SOON_DAYS} 天计为「即将到期」；"
    "6. 合同金额统一折算为万元、保留两位小数，"
    "支持 12.5、12.5万、125000元 等写法，无法识别的金额不计入合同总金额。"
)

_DATE_PATTERNS = [
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"),
    re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
    re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$"),
]

_AMOUNT_PATTERN = re.compile(r"^(-?\d+(?:\.\d+)?)(亿元|亿|万元|万|元)?$")


def parse_date(value: Any) -> date | None:
    """把各种写法的日期解析成 date；认不出来就返回 None，由调用方按「缺失」处理。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        match = pattern.match(text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
    return None


def parse_amount(value: Any) -> float | None:
    """把各种写法的合同金额折算成「万元」；认不出来返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text:
        return None
    match = _AMOUNT_PATTERN.match(text)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or "万元"
    if unit in ("亿元", "亿"):
        return amount * 10000
    if unit == "元":
        return amount / 10000
    return amount


def format_amount(value: Any) -> str:
    """合同金额的规范写法：统一「万元」保留两位小数；无法识别时返回空串。"""
    amount = parse_amount(value)
    if amount is None:
        return ""
    return f"{amount:.2f}万元"


def assess_contract(row: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """对一条运维合同做到期判定，返回列表、动作、统计共用的结论。

    返回字段：
    - display_status: 展示用合同状态（已终止固定不变，超期一律展示为已到期）
    - overdue / expiring_soon / days_remaining: 到期结论与剩余天数
    - expiry: 解析后的到期日期（解析不了为 None）
    - amount: 折算成万元的合同金额（无法识别为 None）
    - note: 到期说明，缺失、异常、超期、临近都按同一口径写清楚
    - abnormal: 日期写法异常（写了但认不出，或到期早于服务期限）
    """
    reference = today or date.today()
    status = str(row.get("status") or "").strip()
    expiry = parse_date(row.get("到期日期"))
    start = parse_date(row.get("服务期限"))
    amount = parse_amount(row.get("合同金额"))

    result: dict[str, Any] = {
        "display_status": status,
        "overdue": False,
        "expiring_soon": False,
        "days_remaining": None,
        "expiry": expiry,
        "amount": amount,
        "note": "",
        "abnormal": False,
    }

    if status == TERMINAL_STATUS:
        result["note"] = "合同已终止，不再判定到期"
        return result

    if expiry is None:
        raw = str(row.get("到期日期") or "").strip()
        result["note"] = "到期日期缺失，按共用算法不判定超期"
        result["abnormal"] = bool(raw)
        return result

    if start is not None and expiry < start:
        result["note"] = "到期日期早于服务期限，按共用算法不判定超期，请核对日期"
        result["abnormal"] = True
        return result

    days_remaining = (expiry - reference).days
    result["days_remaining"] = days_remaining
    if days_remaining < 0:
        result["display_status"] = OVERDUE_STATUS
        result["overdue"] = True
        result["note"] = f"已超期 {-days_remaining} 天"
    elif days_remaining <= EXPIRING_SOON_DAYS:
        result["expiring_soon"] = True
        result["note"] = f"距到期还有 {days_remaining} 天"
    return result
