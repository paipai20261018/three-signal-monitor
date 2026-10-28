"""
定时数据采集脚本（供 GitHub Actions 调用）
抓取 CAPE / QQQ / VIX → 按《定投纳指，真的是最优解吗？》决策树计算 → 写出 data.json
"""
import json
import os
import sys
from datetime import datetime

import signals


def main():
    capital = float(os.environ.get("CAPITAL", "10000"))
    snap = signals.build_snapshot(capital)
    # 精简输出
    out = {
        "generated_at": snap["generated_at"],
        "low_count": snap["low_count"],
        "regime": snap["regime"],
        "action": snap["action"],
        "signals": snap["signals"],
        "raw": {
            "cape": {k: snap["raw"]["cape"].get(k) for k in
                     ("value", "percentile", "as_of", "sample_size")},
            "qqq": {k: snap["raw"]["qqq"].get(k) for k in
                    ("price", "date", "peak", "peak_date", "drawdown", "drop_25d", "near_high")},
            "vix": {k: snap["raw"]["vix"].get(k) for k in ("value", "change")},
        },
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("data.json 写入完成:", out["action"]["title"])


if __name__ == "__main__":
    sys.exit(main())
