# 三信号监控 · 纳指定投决策工具

根据《定投纳指，真的是最优解吗？》一文中的 CAPE + DD + VIX 三信号动态仓位框架，做的实时监控工具。

自动抓取真实数据 → 计算三个信号 → 按原文决策树输出本月操作建议。

## 三个信号（全部实时抓取）

| 信号 | 数据源 | 阈值 |
|---|---|---|
| 估值 CAPE（席勒市盈率） | multpl.com 全历史月度表，自动算分位 | 低位 <20% · 高估 >70% · 泡沫 >85% |
| 回撤 DD（距历史高点） | Nasdaq 官方 API，QQQ 日线约 5 年 | 超跌 <-20% · 25日急跌 <-12% |
| 恐慌 VIX | 腾讯财经实时行情 | 恐慌 >40 · 平静 <12 |

## 决策树（每月第一个交易日执行）

- **2~3 个低位信号** → 大底：3 倍投入 + 弹药仓全打，买 TQQQ
- **1 个低位信号** → 小底：2 倍投入，买 QQQ
- **0 个信号** → 按顺序：25日急跌>12% → 减半杠杆；高估+新高 → 不投；过热/过静 → 卖 1/12 TQQQ；否则正常 1 倍买 QQQ
- **弹药仓**：无信号时每月 1/6 回补 QQQ；低位信号出现全部打出

## 本地运行

```bash
pip install -r requirements.txt
python app.py
# 打开 http://localhost:8000
```

## 部署到免费云平台（推荐 Render）

因为数据源有跨域限制，必须部署后端，不能用纯静态托管（GitHub Pages 不行）。

### 方式 A：Render（免费，推荐）
1. 注册 https://render.com （邮箱即可）
2. New → Web Service → 构建方式选 **Deploy from Git**（先把本目录推到 GitHub）或 **Docker**
3. 免费套餐即可（服务 15 分钟无访问会休眠，打开时唤醒需等 30~60 秒）
4. 部署完成后得到 `https://xxx.onrender.com`，手机浏览器打开 → 「添加到主屏幕」

### 方式 B：Hugging Face Spaces（免费）
1. 注册 https://huggingface.co
2. New Space → 选 **Docker** 模板 → 上传本目录 4 个文件（app.py / signals.py / requirements.txt / Dockerfile / index.html / manifest.json）
3. Space 自带 `https://xxx.hf.space` 地址，可直接访问

### 方式 C：本地常驻
家里有闲置电脑/NAS 的话，`python app.py` 跑起来，手机访问局域网地址。

## 文件说明

| 文件 | 作用 |
|---|---|
| `signals.py` | 核心引擎：抓数据 + 算信号 + 决策树 |
| `app.py` | FastAPI 服务（API + 前端页面） |
| `index.html` | 前端界面（深色主题，手机优先） |
| `Dockerfile` / `requirements.txt` | 部署用 |

## 免责声明

本工具仅为原文策略的可视化监控，数据来自公开免费接口，可能延迟或出错，不构成任何投资建议。
