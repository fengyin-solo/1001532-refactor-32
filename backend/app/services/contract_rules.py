"""运维合同共用口径：到期判断与合同金额的唯一实现。

列表展示、动作流转、统计卡片三处都只能走这里的函数，避免各写一遍导致
「超期条数、合同状态、统计卡对不上」。

到期口径（today 可注入，便于测试）：
1. 已终止的合同保持「已终止」，不再参与任何到期计算，照旧可读；
2. 人工已标记「已到期」的合同维持「已到期」（超期），即使到期日期偏晚；
3. 只有「履行中」的合同按到期日期自动判断：
   - 到期日期缺失或无法识别：状态维持「履行中」，不计超期、不计即将到期，
     给出 expiry_note 说明；
   - 到期日期早于签订/服务起始日期：按日期异常处理，状态维持「履行中」，
     不计超期，给出 expiry_note 说明；
   - 到期日期早于今天：「已到期」（超期）；
   - 到期日期距今天 30 天以内（含今天、含第 30 天）：履行中且「即将到期」；
   - 其余：履行中。
4. 「待签订」等其它状态不参与到期判断，但其日期缺失/异常同样按上述规则给说明。

金额口径：合同金额统一用 parse_amount 解析（兼容千分位、¥/￥、元），
用 format_amount 展示（两位小数、千分位）；统计总金额同样只认 parse_amount。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

STATUS_PENDING = "待签订"
STATUS_ACTIVE = "履行中"
STATUS_EXPIRED = "已到期"
STATUS_TERMINATED = "已终止"

EXPIRING_WINDOW_DAYS = 30


def parse_date(value: Any) -> date | None:
    """把到期日期/服务期限解析成 date；无法识别时返回 None（不抛异常）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    text = text.replace("/", "-").replace(".", "-")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def signing_date(entry: dict[str, Any]) -> date | None:
    """签订日期取「服务期限」的起始日；支持 2026-01-01～2026-12-31 这类写法。"""
    raw = str(entry.get("服务期限") or "").strip()
    if not raw:
        return None
    for separator in ("～", "~", "至"):
        if separator in raw:
            raw = raw.split(separator, 1)[0].strip()
            break
    return parse_date(raw)


def parse_amount(value: Any) -> Decimal | None:
    """把合同金额解析成 Decimal；兼容 120000、'120,000.00'、'¥120000元'。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = str(value).strip()
    if not text:
        return None
    for token in ("¥", "￥", ",", " ", "元"):
        text = text.replace(token, "")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def format_amount(value: Any) -> str:
    """金额唯一展示写法：两位小数 + 千分位；无法解析时显示 —。"""
    amount = value if isinstance(value, Decimal) else parse_amount(value)
    if amount is None:
        return "—"
    return f"{amount.quantize(Decimal('0.01')):,.2f}"


def _expiry_note(entry: dict[str, Any], expiry: date | None) -> str:
    """对缺失、无法识别、早于签订日期的到期日期给出统一说明。"""
    if expiry is None:
        raw = str(entry.get("到期日期") or "").strip()
        if raw:
            return f"到期日期「{raw}」无法识别为日期，未参与到期判断，请核对后补录"
        return "到期日期缺失：无法按日期判断到期，当前状态以人工流转为准，请补录到期日期"
    start = signing_date(entry)
    if start is not None and expiry < start:
        return (
            f"到期日期（{expiry.isoformat()}）早于签订/服务起始日期"
            f"（{start.isoformat()}），按日期异常处理，未计为超期，请核对"
        )
    return ""


def expiry_view(entry: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """计算一条合同的到期视图：status/overdue/expiring/days_to_expiry/expiry_note。

    列表、动作、统计三处都通过本函数读取到期结论，不允许各自再算一遍。
    """
    today = today or date.today()
    stored = str(entry.get("status") or "").strip()
    expiry = parse_date(entry.get("到期日期"))
    days = (expiry - today).days if expiry is not None else None

    if stored == STATUS_TERMINATED:
        return {
            "status": STATUS_TERMINATED,
            "overdue": False,
            "expiring": False,
            "days_to_expiry": None,
            "expiry_note": "",
        }

    note = _expiry_note(entry, expiry)

    if stored == STATUS_EXPIRED:
        # 人工标记（可能提前标记）：维持已到期，按超期统计
        return {
            "status": STATUS_EXPIRED,
            "overdue": True,
            "expiring": False,
            "days_to_expiry": days,
            "expiry_note": note,
        }

    if stored == STATUS_ACTIVE:
        if note or expiry is None:
            # 日期缺失/无法识别/早于签订日期：维持履行中，不计超期
            return {
                "status": STATUS_ACTIVE,
                "overdue": False,
                "expiring": False,
                "days_to_expiry": days,
                "expiry_note": note,
            }
        if expiry < today:
            return {
                "status": STATUS_EXPIRED,
                "overdue": True,
                "expiring": False,
                "days_to_expiry": days,
                "expiry_note": "",
            }
        return {
            "status": STATUS_ACTIVE,
            "overdue": False,
            "expiring": days is not None and 0 <= days <= EXPIRING_WINDOW_DAYS,
            "days_to_expiry": days,
            "expiry_note": "",
        }

    return {
        "status": stored or STATUS_PENDING,
        "overdue": False,
        "expiring": False,
        "days_to_expiry": days,
        "expiry_note": note,
    }
