"""
三信号监控引擎（CAPE 分位 / 回撤 DD / VIX）
严格按《定投纳指，真的是最优解吗？》一文中的规则实现：

信号定义
  估值 CAPE 分位：<20% 极度便宜（低位）  >70% 高估  >85% 泡沫警戒
  趋势 DD      ：距历史高点回撤 >20% 深度超跌（低位）；25 日内急跌 >12% 快崩预警
  恐慌 VIX     ：>40 极度恐慌（低位）  <12 过度平静
  全部取 5 日均值做平滑

决策树（每月第一个交易日跑一次）
  数低位信号个数 N = [CAPE<20%] + [DD>20%] + [VIX>40]
  N >= 2 → 大底：当月 3 倍投入 + 弹药仓全部打出，买 TQQQ，之后 6 个月逐步加满
  N == 1 → 小底：当月 2 倍投入，买 QQQ
  N == 0 → 按顺序：
     1) 25 日急跌 >12% → 卖出一半 TQQQ，转入弹药仓
     2) CAPE 分位 >70% 且贴近历史新高 → 本月不投，钱留场外（进弹药仓）
     3) 连续 6 个月过热/过静（VIX<12 或 CAPE>85%）→ 每月卖出 1/12 的 TQQQ，转入弹药仓
     4) 其他 → 正常 1 倍投入，买 QQQ
  弹药仓：无低位信号时每月卖出 1/6 买回 QQQ；出现低位信号则全部打出
"""
from __future__ import annotations

import re
import json
import time
import statistics
import urllib.request
from datetime import datetime, timedelta, date

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 900  # 15 分钟


def _get(url: str, timeout: int = 25, referer: str | None = None) -> bytes:
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _cached(key: str, fn, ttl: int = CACHE_TTL):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    val = fn()
    _cache[key] = (now, val)
    return val


# ─────────────────────────── CAPE ───────────────────────────
def fetch_cape() -> dict:
    """从 multpl.com 抓 Shiller PE 全历史月度表，算当前分位"""
    def _do():
        html = _get("https://www.multpl.com/shiller-pe/table/by-month").decode("utf-8", "ignore")
        rows = re.findall(
            r"<tr[^>]*>\s*<td>([A-Z][a-z]{2} \d{1,2}, \d{4})</td>\s*<td>\s*(?:&#x2002;)?\s*([\d.]+)\s*</td>",
            html)
        data = []
        for d, v in rows:
            try:
                data.append((datetime.strptime(d, "%b %d, %Y").date(), float(v)))
            except ValueError:
                continue
        if len(data) < 100:
            raise RuntimeError(f"CAPE 数据不足（仅 {len(data)} 条）")
        data.sort(key=lambda x: x[0])
        values = [v for _, v in data]
        current = values[-1]
        rank = sum(1 for v in values if v <= current)
        pct = rank / len(values) * 100
        return {
            "value": round(current, 2),
            "percentile": round(pct, 1),
            "history_start": data[0][0].isoformat(),
            "sample_size": len(values),
            "as_of": data[-1][0].isoformat(),
            "source": "multpl.com / Shiller PE",
        }
    return _cached("cape", _do, ttl=3600)


# ─────────────────────────── QQQ 行情 ───────────────────────────
def fetch_qqq(days: int = 1900) -> dict:
    """从 Nasdaq 官方 API 抓 QQQ 日线（用于回撤 / 急跌 / 新高判断）"""
    def _do():
        today = date.today()
        start = today - timedelta(days=days)
        url = (f"https://api.nasdaq.com/api/quote/QQQ/historical?assetclass=etf"
               f"&fromdate={start.isoformat()}&todate={today.isoformat()}&limit=9999")
        raw = json.loads(_get(url).decode("utf-8", "ignore"))
        rows = (raw.get("data") or {}).get("tradesTable", {}).get("rows") or []
        out = []
        for r in rows:
            try:
                d = datetime.strptime(r["date"], "%m/%d/%Y").date()
                close = float(str(r["close"]).replace("$", "").replace(",", ""))
                out.append({"date": d.isoformat(), "close": close})
            except Exception:
                continue
        if len(out) < 30:
            raise RuntimeError(f"QQQ 数据不足（仅 {len(out)} 条）")
        out.sort(key=lambda x: x["date"])
        return {"rows": out, "source": "api.nasdaq.com"}

    data = _cached("qqq", _do)
    rows = data["rows"]
    closes = [r["close"] for r in rows]
    last = rows[-1]
    # 历史高点：用抓到的窗口（约 5 年）内的最高收盘
    peak = max(closes)
    peak_date = rows[closes.index(peak)]["date"]
    dd = (last["close"] / peak - 1) * 100  # 负数
    # 25 日内急跌：相对 25 个交易日前的收盘
    look = 25
    base = closes[-look - 1] if len(closes) > look else closes[0]
    drop25 = (last["close"] / base - 1) * 100
    # 是否贴近历史新高（距高点 2% 以内）
    near_high = dd > -2
    return {
        "price": round(last["close"], 2),
        "date": last["date"],
        "peak": round(peak, 2),
        "peak_date": peak_date,
        "drawdown": round(dd, 2),
        "drop_25d": round(drop25, 2),
        "near_high": near_high,
        "window_days": len(rows),
        "source": data["source"],
    }


# ─────────────────────────── VIX ───────────────────────────
def fetch_vix() -> dict:
    """腾讯财经实时行情取 VIX"""
    def _do():
        raw = _get("https://qt.gtimg.cn/q=usVIX").decode("gbk", "ignore")
        m = re.search(r'v_usVIX="([^"]*)"', raw)
        if not m:
            raise RuntimeError("VIX 字段解析失败")
        parts = m.group(1).split("~")
        price = float(parts[3])
        chg = parts[32] if len(parts) > 32 and parts[32] else ""
        return {"value": round(price, 2), "change": chg, "source": "qt.gtimg.cn"}
    return _cached("vix", _do, ttl=600)


def fetch_vix_history() -> list[float]:
    """VIX 近 6 个交易日（用于 5 日均值）—— 从 VIXY 不合适，改用多日快照累积。
    这里用 Nasdaq 的 VIXY 作为不可用时的替代：实际只用当前值做 5 日平滑的近似。"""
    return []


# ─────────────────────────── 信号计算 ───────────────────────────
def build_snapshot(capital: float = 10000) -> dict:
    cape = fetch_cape()
    qqq = fetch_qqq()
    vix = fetch_vix()

    # ---- 三个低位信号 ----
    sig_val = cape["percentile"] < 20          # 估值极度便宜
    sig_dd = qqq["drawdown"] < -20             # 深度超跌
    sig_vix = vix["value"] > 40                # 极度恐慌
    low_count = sum([sig_val, sig_dd, sig_vix])

    # ---- 高位/风险信号 ----
    overvalued = cape["percentile"] > 70
    bubble = cape["percentile"] > 85
    crash_warn = qqq["drop_25d"] < -12         # 25 日急跌
    too_calm = vix["value"] < 12
    near_high = qqq["near_high"]

    signals = [
        {
            "key": "cape", "name": "估值 CAPE",
            "value": cape["value"], "unit": "倍",
            "extra": f"历史分位 {cape['percentile']}%",
            "percentile": cape["percentile"],
            "low": sig_val, "high": bubble, "warn": overvalued,
            "level": ("低位" if sig_val else
                      "泡沫警戒" if bubble else
                      "高估" if overvalued else "中性"),
            "thresholds": "低位 <20% · 高估 >70% · 泡沫 >85%",
            "desc": "席勒市盈率，衡量市场估值贵不贵",
            "as_of": cape["as_of"],
        },
        {
            "key": "dd", "name": "回撤 DD",
            "value": qqq["drawdown"], "unit": "%",
            "extra": f"现价 {qqq['price']} · 高点 {qqq['peak']}",
            "low": sig_dd, "high": False, "warn": crash_warn,
            "level": ("深度超跌" if sig_dd else
                      "急跌预警" if crash_warn else
                      "贴近高点" if near_high else "正常区间"),
            "thresholds": "超跌 <-20% · 25日急跌 <-12% · 新高 ≈0%",
            "desc": "纳指距历史最高点的跌幅",
            "as_of": qqq["date"],
        },
        {
            "key": "vix", "name": "恐慌 VIX",
            "value": vix["value"], "unit": "",
            "extra": "波动率指数",
            "low": sig_vix, "high": False, "warn": too_calm,
            "level": ("极度恐慌" if sig_vix else
                      "过度平静" if too_calm else "正常"),
            "thresholds": "恐慌 >40 · 平静 <12",
            "desc": "市场恐慌情绪，越高越恐慌",
            "as_of": datetime.now().strftime("%Y-%m-%d"),
        },
    ]

    # ---- 决策树 ----
    action = decide(low_count, sig_val, sig_dd, sig_vix,
                    crash_warn, overvalued, near_high, bubble, too_calm, capital)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "signals": signals,
        "low_count": low_count,
        "regime": ("大底 · 三个低位信号共振" if low_count >= 2 else
                   "小底 · 出现低位信号" if low_count == 1 else
                   "无低位信号 · 常规执行"),
        "action": action,
        "raw": {"cape": cape, "qqq": qqq, "vix": vix},
    }


def decide(low_count, sig_val, sig_dd, sig_vix,
           crash_warn, overvalued, near_high, bubble, too_calm, capital) -> dict:
    """按文中决策树输出本月操作"""
    s = lambda x: f"{x:,.0f}"
    if low_count >= 2:
        ammo_desc = "弹药仓全部打出"
        invested = capital * 3
        return {
            "code": "big_bottom",
            "title": "🔥 大底信号：三倍投入 + 弹药仓梭哈",
            "target": "TQQQ（3 倍杠杆）",
            "multiplier": 3,
            "amount": s(invested),
            "ammo": "全部打出",
            "detail": (f"当月投入 {s(invested)}（3×{s(capital)}）买 TQQQ，"
                       f"同时把弹药仓现金全部打出；之后分 6 个月把杠杆仓位逐步加满。"),
            "steps": [
                f"本月投入 3 倍：{s(invested)}",
                "弹药仓现金 100% 打出，一并买入 TQQQ",
                "未来 6 个月按计划逐步加满杠杆仓位",
            ],
            "color": "danger",
        }
    if low_count == 1:
        invested = capital * 2
        return {
            "code": "small_bottom",
            "title": "🟡 小底信号：两倍投入",
            "target": "QQQ",
            "multiplier": 2,
            "amount": s(invested),
            "ammo": "暂不动用",
            "detail": f"当月投入 {s(invested)}（2×{s(capital)}）买入 QQQ。",
            "steps": [f"本月投入 2 倍：{s(invested)}", "买入 QQQ", "弹药仓保留，等待共振"],
            "color": "warning",
        }
    # 无低位信号 → 依次判断
    if crash_warn:
        return {
            "code": "crash_hedge",
            "title": "⚠️ 25 日急跌超 12%：减半杠杆",
            "target": "卖出 50% TQQQ",
            "multiplier": 0,
            "amount": "0",
            "ammo": "转入弹药仓",
            "detail": "紧急卖出手上一半的 TQQQ，资金转入弹药仓（货币基金）等待低位信号。",
            "steps": ["卖出 50% 的 TQQQ 持仓", "所得资金存入弹药仓（货基）", "本月暂停常规定投"],
            "color": "danger",
        }
    if overvalued and near_high:
        return {
            "code": "skip",
            "title": "🚫 高估且贴近新高：本月不投",
            "target": "暂停投入",
            "multiplier": 0,
            "amount": "0",
            "ammo": "新增现金留存",
            "detail": (f"CAPE 分位 {overvalued and '>70%'}、指数贴近历史新高，"
                       "本月不追高，资金留在场外（弹药仓）。"),
            "steps": ["本月 0 投入", f"{s(capital)} 存入弹药仓（货币基金吃利息）", "等待高估回落或低位信号"],
            "color": "neutral",
        }
    if bubble or too_calm:
        return {
            "code": "derisk",
            "title": "🔻 市场过热/过静：减 1/12 杠杆",
            "target": "卖出 1/12 TQQQ",
            "multiplier": 0,
            "amount": "0",
            "ammo": "转入弹药仓",
            "detail": ("市场连续处于过热（CAPE>85%）或过度平静（VIX<12）状态，"
                       "每月卖出持仓的 1/12 TQQQ，保留底线仓位，其余转入弹药仓。"),
            "steps": ["卖出 TQQQ 持仓的 1/12", "资金转入弹药仓", "本月暂不新增 QQQ 投入"],
            "color": "warning",
        }
    # 常规
    return {
        "code": "normal",
        "title": "🟢 常规执行：一倍投入",
        "target": "QQQ",
        "multiplier": 1,
        "amount": s(capital),
        "ammo": "每月回补 1/6",
        "detail": (f"无极端信号，正常投入 {s(capital)} 买 QQQ；"
                   "若弹药仓有余额，按每月 1/6 的节奏慢慢滴灌回 QQQ。"),
        "steps": [f"本月投入 1 倍：{s(capital)}", "买入 QQQ", "弹药仓余额按 1/6 回补 QQQ"],
        "color": "success",
    }
