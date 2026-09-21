# chunk Web 界面

## 架构

支持两种运行方式：

1. **单进程模式（推荐）**：`web/app.py` 同时提供后端 API 和静态文件服务。
2. **双进程模式**：`web/frontend.py` (:58001) 代理到 `web/app.py` (:58002)。

```
Browser
    ↓
:58002  web/app.py  (API + static)
```

或

```
Browser :58001
    ↓
Frontend (static SPA + API proxy)
    ↓
:58002
    ↓
Backend API (pipeline orchestration)
```

## 启动

```bash
# 单进程启动（推荐，同时服务 API 和静态页面）
python web/app.py

# 同时启动前后端（自动选用 venv/ 或 .venv/ 的解释器，均不存在时用当前解释器）
python web/start.py

# 或用控制脚本
./web/ctl.sh start | stop | restart | status

# 单独启动
python web/app.py          # 后端 58002 + 静态文件
python web/frontend.py     # 前端 58001
```

## 额外依赖

```bash
pip install flask requests
```

## 模块说明

| 文件 | 端口 | 职责 |
|------|------|------|
| `web/app.py` | 58002 | 后端 REST API：config、upload、upload/batch、process、tasks、query、index、log_patterns/*；同时通过 `/static/` 提供 SPA |
| `web/frontend.py` | 58001 | 静态文件服务，代理 `/api/*` 到后端 |
| `web/static/index.html` | — | SPA：config / import / tasks / query / logpatterns 五个标签页 |
| `web/static/app.js` | — | 前端逻辑：API 调用、拖拽上传、ZIP 上传、任务轮询、查询结果展示、日志模式导入 |
| `web/static/style.css` | — | 样式 |
| `web/start.py` | — | 同时启动前后端，处理 Ctrl+C |

## 关键设计

- 上传文件保存到 `web/uploads/`。
- 支持 `.zip` 上传：自动解压并定位主 Markdown 文件，便于处理含本地图片的 Markdown。
- 处理任务在 `ThreadPoolExecutor` 中异步执行。
- 任务状态保存在内存中。
- 前端反向代理 API 调用以避免 CORS（双进程模式）。
- 配置页支持图片处理后端切换（local/remote）及远程 Base URL、模型、API Key 设置。
- 配置页 Qdrant 区可单独设置日志模式库 Collection（`log_pattern_collection_name`），与文档库 Collection 区分。

## 日志模式导入 API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/log_patterns/import` | POST | multipart 文件上传（JSON/YAML/CSV/TSV/XLSX/XLS），form 字段 `collection_name` 可选 |
| `/api/log_patterns/import_json` | POST | 内联 JSON body：`{"patterns": [...], "collection_name": 可选}` |
| `/api/log_patterns/collections` | GET | 返回当前日志模式目标 collection 配置与 Qdrant 现有集合列表 |

导入响应返回 `patterns` / `valid_patterns` / `standard_chunks` / `mini_chunks` / `collection` / `total_points` / `validation_errors` 摘要。部分模式校验失败时返回 HTTP 207，其余正常导入。

前端「日志模式导入」标签页支持两种方式：
- **文件上传**：拖拽或选择结构化模式文件
- **纯文本 JSON**：粘贴模式数组或 `{"patterns": [...]}` 文本直接导入

目标 Collection 输入框留空时使用配置页设置的 `log_pattern_collection_name`。
