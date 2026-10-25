# dsh-mem0

给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（DSH）用的长期记忆插件：**mem0 语义记忆 + 持久主题图 + 用户画像**，自带全屏记忆页。

单机运行、零外部数据库：向量存在本地 Chroma（SQLite），抽取与 embedding 走你自己的 API（默认 DeepSeek + 硅基流动 bge-m3）。

## 功能

- **自动召回**：每轮把画像与相关事实挂进系统提示（`systemPrompt.context`，不伪造消息、不改写用户输入）
- **白天只追加**：会话结束或闲置 N 分钟后，一次模型调用抽事实直接入库，不做比对，成本最低
- **夜间批量整理**：精确去重 → LLM 逐对归纳同一事实 → 矛盾处理（保留较新）→ 主题图同步 → 卡片/画像 → git 同步
- **持久主题图**：主题是稳定节点（带中心向量与演化历史），数量由内容决定；新事实按语义归入，相近主题合并，长期不用自动归档
- **用户画像**：`PROFILE.md` 四板块（身份/偏好/观察/待确认），配 `profile_get` / `profile_update` 工具
- **按需检索**：`memory_search` 工具
- **快照与撤销**：任何破坏性操作前自动快照（保留最近 20 份），面板一键回滚
- **全屏记忆页**：左侧边栏入口 + 全屏页面；状态 pills、记忆列表（搜索/新增/多选合并/删除）、主题卡、主题图（滚轮缩放、拖拽平移）
- **⌘K 搜索**：命令面板快速定位记忆

## 架构

```
DSH 插件（index.js / client.js）
  ├─ 托管本地 Python 服务（uvicorn，默认 127.0.0.1:18762）
  ├─ 代理 /mem0 面板路由
  ├─ agent/pre-step            → 异步召回，写入缓存
  ├─ systemPrompt.context      → 同步渲染「画像 + 相关记忆」
  ├─ agent/assistant-stream    → 累积助手回复
  ├─ agent/disposed / 闲置定时器 → 捕获对话（有序 user/assistant）
  ├─ tools                     → memory_search / profile_get / profile_update
  └─ 每天 03:30（Asia/Shanghai）→ 去重 → 归纳 → 矛盾 → 主题图 → 同步
Python 服务（server/app.py）
  └─ mem0 + Chroma + 主题图 + 卡片/画像文件 + 快照 + git 同步
```

## 安装

```sh
export MEM0_HOME="$HOME/.dsh-mem0"
mkdir -p "$MEM0_HOME"
python3 -m venv "$MEM0_HOME/.venv"
"$MEM0_HOME/.venv/bin/pip" install mem0ai chromadb fastapi uvicorn httpx spacy
"$MEM0_HOME/.venv/bin/python" -m spacy download zh_core_web_sm   # mem0 抽实体需要
cp -r server export_mem.py sync.sh "$MEM0_HOME"/
cp config.example.json "$MEM0_HOME/config.json"    # 填入你的 API Key

dsh plugin --profile web add <本仓库地址或本地路径>
```

`config.json` 至少改两处 `api_key`：抽取用的 LLM 与 embedding（OpenAI 兼容接口即可）。

## 配置项（插件设置页）

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | true | 总开关 |
| `recallEnabled` / `recallLimit` / `recallMinScore` / `recallTimeoutMs` | true / 5 / 0.45 / 600 | 自动召回 |
| `captureEnabled` / `captureMode` / `captureIdleMinutes` / `captureMaxChars` | true / session-end / 30 / 6000 | 自动写入 |
| `consolidateEnabled` / `consolidateAt` / `consolidateThreshold` | true / 03:30 / 0.93 | 夜间去重 |
| `mergeEnabled` | true | 夜间 LLM 归纳同一事实的不同表述 |
| `supersedeEnabled` / `supersedeMinOverlap` | true / 3 | 矛盾处理 |
| `cardsEnabled` | true | 主题图与卡片生成 |
| `syncEnabled` / `syncHours` | true / 6 | 定期推送到 git |
| `panelEnabled` | true | `/mem0` 面板 |

## 主要接口

```
GET  /status              状态卡数据
GET  /list  /stats  /export
POST /search /add /update /delete
POST /capture             完整比对写入（旧路径）
POST /capture_append      白天纯追加（一次模型调用）
POST /consolidate         精确去重
POST /merge_duplicates    逐对归纳同一事实
POST /supersede           矛盾处理
POST /topics/sync         主题图增量同步
GET  /topics/list  /topics/graph
POST /topics/add          手动创建 pinned 主题
GET  /cards/list  /cards/read
GET  /snapshots/list  POST /snapshots/restore
POST /memories/bulk_delete  /memories/merge
POST /nightly/run         手动触发完整整理
```

## 设计取舍

- **相似不等于等价**：字符串包含会被否定句骗过（「玩A股」⊂「不玩A股」），所以相似度只做「疑似重复」报告
- **归纳只做成对判定**：不让模型直接聚类，避免把「同一主题的不同要求」并成一条
- **注入走系统提示**：不伪造 user 消息，避免破坏宿主消息序列语义
- **破坏性操作先快照**：合并、删除、整理前都留一份，可一键回滚

## 许可

MIT
