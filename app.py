"""
三信号监控服务
  GET  /                 → 前端页面
  GET  /api/snapshot     → 当前三信号 + 本月决策（capital 参数可选，默认 10000）
  GET  /api/history      → 关键指标历史序列（CAPE 月度 / QQQ 日线回撤）
  POST /api/refresh      → 清空缓存强制刷新
"""
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import signals

BASE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="三信号监控")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "index.html"), media_type="text/html")


@app.get("/api/snapshot")
def snapshot(capital: float = Query(10000, gt=0)):
    try:
        return signals.build_snapshot(capital)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/api/history")
def history():
    """返回 CAPE 月度序列 + QQQ 回撤序列，用于画趋势"""
    try:
        cape = signals.fetch_cape()
        qqq = signals.fetch_qqq()
        rows = qqq["rows"]
        closes = [r["close"] for r in rows]
        # 逐日回撤
        peak = -1e9
        dd_series = []
        for r in rows:
            peak = max(peak, r["close"])
            dd_series.append({"date": r["date"], "dd": round((r["close"] / peak - 1) * 100, 2)})
        return {
            "cape": cape,
            "qqq": qqq,
            "dd_series": dd_series[::5],  # 每 5 天取一点，减小体积
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/refresh")
def refresh():
    signals._cache.clear()
    return {"ok": True, "message": "缓存已清空，下次请求重新抓取"}


@app.get("/api/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
