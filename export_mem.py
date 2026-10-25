#!/usr/bin/env python3
"""把 mem0 里的记忆全量导出成 JSON + Markdown，供 git 同步。"""
import json, os, logging, datetime
os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger().setLevel(logging.ERROR)
from mem0 import Memory

BASE = os.environ.get("MEM0_HOME", os.path.join(os.path.expanduser("~"), ".dsh-mem0"))
OUT = os.path.join(BASE, "repo")
os.makedirs(OUT, exist_ok=True)
TZ = datetime.timezone(datetime.timedelta(hours=8))

m = Memory.from_config(json.load(open(os.path.join(BASE, "config.json"))))
# 必须显式传 top_k：mem0 的 get_all 默认只返回 20 条
r = m.get_all(filters={"user_id": "owner"}, top_k=100000)
items = r.get("results") if isinstance(r, dict) else (r or [])

now = datetime.datetime.now(TZ)
stamp = now.strftime("%Y-%m-%d %H:%M:%S")

tmp = os.path.join(OUT, "memories.json.tmp")
with open(tmp, "w") as f:
    json.dump({"exported_at": stamp, "user": "owner", "count": len(items), "memories": items},
              f, ensure_ascii=False, indent=1)
os.replace(tmp, os.path.join(OUT, "memories.json"))

lines = ["# DSH 长期记忆", "", f"导出时间：{stamp}　共 {len(items)} 条", ""]
for it in sorted(items, key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True):
    lines.append(f"- {it.get('memory')}")
lines.append("")
tmp2 = os.path.join(OUT, "MEMORY.md.tmp")
open(tmp2, "w").write("\n".join(lines))
os.replace(tmp2, os.path.join(OUT, "MEMORY.md"))
print(f"导出 {len(items)} 条 → {OUT}")
