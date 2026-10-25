#!/usr/bin/env python3
"""mem0 记忆服务：给 dsh 插件和面板用的本地 HTTP 接口。"""
import json, os, logging, subprocess, datetime, shutil, time, threading, uuid
from typing import List, Optional

os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger().setLevel(logging.ERROR)

from fastapi import FastAPI
from pydantic import BaseModel, Field
from mem0 import Memory

BASE = os.environ.get("MEM0_HOME", os.path.join(os.path.expanduser("~"), ".dsh-mem0"))
TZ = datetime.timezone(datetime.timedelta(hours=8))
CFG = os.environ.get("MEM0_CONFIG", os.path.join(BASE, "config.json"))
USER = "owner"

app = FastAPI(title="dsh-mem0")
_mem: Optional[Memory] = None
_mem_lock = threading.Lock()
_write_lock = threading.Lock()   # 所有写操作串行化（P1-9）


def mem() -> Memory:
    global _mem
    with _mem_lock:
        if _mem is None:
            _mem = Memory.from_config(json.load(open(CFG)))
    return _mem


@app.on_event("startup")
def _warmup():
    """启动即在主线程初始化 mem0，避免线程池里首次初始化触发 Chroma 缓存竞态。"""
    try:
        mem()
    except Exception:
        pass


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class AddIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    user: str = USER


class UpdateIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)


class DeleteIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)


class CaptureIn(BaseModel):
    texts: List[str] = Field(default_factory=list, max_length=64)
    user: str = USER
    run_id: Optional[str] = None
    max_chars: int = Field(default=6000, ge=500, le=20000)
    messages: List[dict] = Field(default_factory=list, max_length=80)


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.datetime.now().isoformat(timespec="seconds")}


@app.get("/list")
def list_all(user: str = USER):
    r = mem().get_all(filters={"user_id": user}, top_k=100000)
    items = r.get("results") if isinstance(r, dict) else (r or [])
    return {"count": len(items), "items": items}


@app.post("/search")
def search(body: SearchIn):
    r = mem().search(body.query, filters={"user_id": USER}, top_k=body.limit)
    items = r.get("results") if isinstance(r, dict) else (r or [])
    items = [x for x in items if (x.get("score") or 0) >= body.min_score]
    return {"items": items}


@app.post("/add")
def add(body: AddIn):
    with _write_lock:
        r = mem().add(body.text, user_id=body.user)
    return {"results": r.get("results") if isinstance(r, dict) else r}


@app.post("/update")
def update(body: UpdateIn):
    _snapshot("update")
    with _write_lock:
        mem().update(body.id, body.text)
    return {"ok": True}


@app.post("/delete")
def delete(body: DeleteIn):
    _snapshot("delete")
    with _write_lock:
        mem().delete(body.id)
    return {"ok": True}


@app.post("/capture")
def capture(body: CaptureIn):
    """把一段对话交给 mem0 抽取入库（带会话 run_id 隔离，P1-4）。"""
    text = "\n".join(t for t in body.texts if t)[: body.max_chars]
    if not text.strip() and body.messages:
        text = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in body.messages
                          if isinstance(m, dict) and isinstance(m.get("content"), str))[: body.max_chars]
    if not text.strip():
        return {"ok": False, "reason": "empty"}
    kwargs = {"user_id": body.user}
    if body.run_id:
        kwargs["run_id"] = body.run_id
    # 有有序 user/assistant 列表时按官方格式传，否则退回字符串（P1-3）
    msgs = [m for m in body.messages if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    payload = msgs if len(msgs) >= 2 else text
    r = mem().add(payload, **kwargs)
    res = r.get("results") if isinstance(r, dict) else r
    return {"ok": True, "added": len(res or []), "truncated": len(text) >= body.max_chars, "results": res}


@app.get("/stats")
def stats():
    r = mem().get_all(filters={"user_id": USER}, top_k=100000)
    items = r.get("results") if isinstance(r, dict) else (r or [])
    last = ""
    log = os.path.join(BASE, "sync.log")
    if os.path.exists(log):
        lines = [l for l in open(log).read().strip().split("\n") if l]
        last = lines[-1] if lines else ""
    return {"count": len(items), "last_sync": last}


@app.post("/sync")
def sync():
    p = subprocess.run(["/bin/sh", os.path.join(BASE, "sync.sh")], capture_output=True, text=True, timeout=300)
    tail = ""
    log = os.path.join(BASE, "sync.log")
    if os.path.exists(log):
        tail = open(log).read().strip().split("\n")[-1]
    return {"ok": p.returncode == 0, "tail": tail}


@app.get("/export")
def export():
    r = mem().get_all(filters={"user_id": USER}, top_k=100000)
    items = r.get("results") if isinstance(r, dict) else (r or [])
    return {"exported_at": datetime.datetime.now().isoformat(timespec="seconds"), "count": len(items), "memories": items}


@app.get("/")
def panel():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(open(os.path.join(BASE, "server", "panel.html"), encoding="utf-8").read())


class CaptureAppendIn(BaseModel):
    texts: List[str] = Field(default_factory=list, max_length=64)
    messages: List[dict] = Field(default_factory=list, max_length=80)
    user: str = USER
    run_id: Optional[str] = None
    max_chars: int = Field(default=6000, ge=500, le=20000)
    dry_run: bool = False


@app.post("/capture_append")
def capture_append(body: CaptureAppendIn):
    """白天模式：只做一次事实抽取，直接写库，不调比对模型（省一半成本）。

    重复/近义条目留给每天凌晨的 /merge_duplicates 统一归纳。
    """
    text = "\n".join(t for t in body.texts if t)[: body.max_chars]
    if not text.strip() and body.messages:
        text = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in body.messages
                          if isinstance(m, dict) and isinstance(m.get("content"), str))[: body.max_chars]
    if not text.strip():
        return {"ok": False, "reason": "empty"}

    cfg = json.load(open(CFG))
    prompt_cfg = cfg.get("custom_fact_extraction_prompt") or '抽取值得长期记住的事实，输出 JSON：{"facts": ["事实1"]}。'
    prompt = f"{prompt_cfg}\n\n对话：\n{text}"
    try:
        data = _llm_json(prompt, timeout=120)
    except Exception as e:
        return {"ok": False, "reason": "llm_failed", "error": str(e)}
    facts = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list):
        return {"ok": False, "reason": "bad_llm_output"}

    clean = []
    for f in facts:
        if isinstance(f, str) and f.strip() and len(f.strip()) <= 500:
            clean.append(f.strip())
    clean = list(dict.fromkeys(clean))[:20]
    if body.dry_run:
        return {"ok": True, "dry_run": True, "facts": clean, "added": len(clean)}

    metadata = {"user_id": body.user}
    if body.run_id:
        metadata["run_id"] = body.run_id
    mem_ = mem()
    ids = []
    for fact in clean:
        try:
            ids.append(mem_._create_memory(fact, {}, metadata=dict(metadata)))
        except Exception as e:
            return {"ok": False, "reason": "insert_failed", "error": str(e), "added": len(ids)}
    return {"ok": True, "added": len(ids), "ids": ids, "facts": clean}


class ConsolidateIn(BaseModel):
    threshold: float = Field(default=0.93, ge=0.8, le=1.0)
    dry_run: bool = False


def _norm(s: str) -> str:
    import re
    return re.sub(r"[\s，。！？、,.!?~～]+", "", (s or "").lower())


@app.post("/consolidate")
def consolidate(body: ConsolidateIn):
    """去重整理：完全重复直接删；语义相似度 >= threshold 的合并保留更完整的一条。"""
    m = mem()
    r = m.get_all(filters={"user_id": USER}, top_k=100000)
    items = r.get("results") if isinstance(r, dict) else (r or [])
    items = [x for x in items if x.get("memory")]

    deleted, merged = [], []
    # 1) 规范化后完全重复
    seen = {}
    for it in items:
        k = _norm(it["memory"])
        if k in seen:
            loser = it if len(it["memory"]) <= len(seen[k]["memory"]) else seen[k]
            keep = seen[k] if loser is it else it
            seen[k] = keep
            if not body.dry_run:
                try: m.delete(loser["id"])
                except Exception: pass
            deleted.append({"id": loser["id"], "memory": loser["memory"], "reason": "exact"})
        else:
            seen[k] = it

    survivors = list(seen.values())
    # 2) 语义近似
    emb = m.embedding_model.embed
    vecs = []
    for it in survivors:
        try:
            vecs.append((it, emb(it["memory"], "search")))
        except Exception:
            pass

    def cos(a, b):
        import math
        dot = sum(x*y for x, y in zip(a, b))
        na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
        return dot/(na*nb) if na and nb else 0.0

    killed = set()
    for i in range(len(vecs)):
        if i in killed: continue
        for j in range(i+1, len(vecs)):
            if j in killed: continue
            if i in killed: break          # 左项已被删，停止用它对后续项做判断（P0-4）
            a, va = vecs[i]; b, vb = vecs[j]
            sim = cos(va, vb)
            if sim < body.threshold:
                continue
            # 相似不等于等价：字符串包含会被否定句骗过（「玩A股」⊂「不玩A股」），
            # 所以相似度只做「疑似重复」报告，一律不删（P0-3）
            merged.append({"kept": a["memory"], "removed": None,
                           "suspected_duplicate": b["memory"], "score": round(sim, 4),
                           "skipped": "相似但不等价，未删除，请人工确认"})

    return {"before": len(items), "deleted_exact": deleted, "merged_similar": merged,
            "after": len(items) - len(deleted) - len(merged), "dry_run": body.dry_run}


class ConflictIn(BaseModel):
    pairs: int = Field(default=40, ge=1, le=200)
    dry_run: bool = False


def _llm_conflict(pairs):
    """把若干「同主题但不同」的记忆对交给 DeepSeek 判断是否矛盾。"""
    import httpx
    cfg = json.load(open(CFG))
    key = cfg["llm"]["config"]["api_key"]
    base = cfg["llm"]["config"].get("openai_base_url", "https://api.deepseek.com/v1")
    model = cfg["llm"]["config"].get("model", "deepseek-chat")
    lines = []
    for idx, (a, b) in enumerate(pairs):
        lines.append(f"{idx}. A: {a}\n   B: {b}")
    prompt = (
        "下面是一些成对的用户长期记忆条目。请判断每一对是否互相矛盾（事实冲突或后者推翻前者）。\n"
        "只输出真正矛盾的对，不矛盾的完全省略。只输出 JSON 数组，不要解释。格式：\n"
        '[{"i":0,"conflict":true,"keep":"B","reason":"简短中文原因"}]\n'
        'keep 取值 "A" 或 "B"，表示应保留哪条（通常保留更新的）；不矛盾的对就不要出现在输出里。\n\n'
        + "\n".join(lines)
    )
    r = httpx.post(f"{base}/chat/completions", timeout=120,
                   headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                   json={"model": model, "messages": [{"role": "user", "content": prompt}],
                         "temperature": 0, "response_format": {"type": "json_object"}})
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    import re as _re
    arr = json.loads(content) if content.strip().startswith("[") else json.loads(content).get("items", [])
    return arr


STOP = {
    "用户", "的是", "一个", "可以", "现在", "而且", "因为", "所以", "如果", "然后", "还是", "这个", "那个",
    "要求", "设定", "需要", "自动", "时间", "分钟", "小时", "触发", "标准", "写入", "总结", "各做",
    "一次", "发布", "内容", "之后", "已经", "没有", "就是", "不是", "什么", "怎么", "我们", "他们",
}


def _grams(s: str):
    import re
    s = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", s or "")
    return {s[i:i+2] for i in range(len(s) - 1)}


def _overlap(a: str, b: str) -> int:
    return len((_grams(a) & _grams(b)) - STOP)


class SupersedeIn(BaseModel):
    min_overlap: int = Field(default=3, ge=2, le=8)
    max_pairs: int = Field(default=60, ge=1, le=300)
    dry_run: bool = False


@app.post("/supersede")
def supersede(body: SupersedeIn):
    """矛盾记忆处理：关键词重叠够高 + 模型判定矛盾 → 删掉较旧那条。
    其余情况只进报告，不动数据。"""
    m = mem()
    r = m.get_all(filters={"user_id": USER}, top_k=100000)
    items = [x for x in (r.get("results") if isinstance(r, dict) else (r or [])) if x.get("memory")]

    cands, meta = [], []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ov = _overlap(items[i]["memory"], items[j]["memory"])
            if ov < body.min_overlap:
                continue
            cands.append((items[i]["memory"], items[j]["memory"]))
            meta.append((items[i], items[j]))
    cands, meta = cands[:body.max_pairs], meta[:body.max_pairs]
    if not cands:
        return {"candidates": 0, "applied": [], "reported": []}

    try:
        verdicts = _llm_conflict(cands)
    except Exception as e:
        return {"candidates": len(cands), "error": str(e), "applied": [], "reported": []}

    # 先整批校验，非法项整条丢弃（P0-6）
    plans, used = [], set()
    for v in (verdicts if isinstance(verdicts, list) else []):
        if not isinstance(v, dict) or v.get("conflict") is not True:
            continue
        if v.get("keep") not in ("A", "B"):
            continue
        i = v.get("i")
        if type(i) is not int or not (0 <= i < len(meta)) or i in used:
            continue
        used.add(i)
        plans.append((i, v))

    applied, reported = [], []
    for idx, v in plans:
        a, b = meta[idx]
        ta = str(a.get("updated_at") or a.get("created_at") or "")
        tb = str(b.get("updated_at") or b.get("created_at") or "")
        if not ta or not tb or ta == tb:
            reported.append({"keep": a["memory"], "drop": b["memory"], "reason": "时间缺失或相同，未自动删除", "skipped": True})
            continue
        newer = a if ta > tb else b
        older = b if newer is a else a
        entry = {"keep": newer["memory"], "drop": older["memory"], "reason": v.get("reason", "")}
        if body.dry_run:
            reported.append(entry); continue
        try:
            m.delete(older["id"])
            applied.append(entry)
        except Exception as e:
            reported.append({**entry, "error": str(e)})
    return {"candidates": len(cands), "applied": applied, "reported": reported, "dry_run": body.dry_run}


CARDS = os.path.join(BASE, "cards")


def _embed_batch(texts, timeout=120):
    """批量 embedding：走 embedder 配置的 OpenAI 兼容 /embeddings（每次最多 64 条）。"""
    import httpx
    cfg = json.load(open(CFG))
    ec = cfg["embedder"]["config"]
    key = ec.get("api_key")
    base = ec.get("openai_base_url", "https://api.siliconflow.cn/v1")
    model = ec.get("model")
    out = []
    for i in range(0, len(texts), 64):
        chunk = texts[i:i+64]
        r = httpx.post(f"{base}/embeddings", timeout=timeout,
                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                       json={"model": model, "input": chunk})
        r.raise_for_status()
        data = r.json().get("data") or []
        if len(data) != len(chunk):
            raise RuntimeError("embedding 返回条数不一致")
        out.extend([d["embedding"] for d in sorted(data, key=lambda x: x.get("index", 0))])
    return out


def _llm_json(prompt, timeout=180):
    import httpx
    cfg = json.load(open(CFG))
    key = cfg["llm"]["config"]["api_key"]
    base = cfg["llm"]["config"].get("openai_base_url", "https://api.deepseek.com/v1")
    model = cfg["llm"]["config"].get("model", "deepseek-chat")
    r = httpx.post(f"{base}/chat/completions", timeout=timeout,
                   headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                   json={"model": model, "messages": [{"role": "user", "content": prompt}],
                         "temperature": 0, "response_format": {"type": "json_object"}})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


class MergeIn(BaseModel):
    batch: int = Field(default=70, ge=20, le=120)
    candidate_threshold: float = Field(default=0.86, ge=0.5, le=1.0)
    max_candidates: int = Field(default=120, ge=10, le=400)
    dry_run: bool = False


@app.post("/merge_duplicates")
def merge_duplicates(body: MergeIn):
    """凌晨归纳：先按向量相似度找候选对，再让模型逐对判定是否「同一事实的不同表述」。

    白天的 /capture_append 只追加不比对，近义重复在这里统一清理。
    只处理**成对**的候选（不做多条目聚类），避免把「同一主题的不同要求」并成一条。
    """
    m = mem()
    r = m.get_all(filters={"user_id": USER}, top_k=100000)
    items = r.get("results") if isinstance(r, dict) else (r or [])
    items = [it for it in items if isinstance(it.get("memory"), str) and it["memory"].strip()]
    if len(items) < 2:
        return {"total": len(items), "candidates": 0, "groups": [], "deleted": [], "dry_run": body.dry_run}

    # ---- 1) 批量 embedding，挑出高相似候选对 ----
    try:
        matrix = _embed_batch([it["memory"] for it in items])
    except Exception as e:
        matrix = None
        logger.warning("embed_batch 失败，退回逐条：%s", e)
        try:
            matrix = [m.embedding_model.embed(it["memory"], "add") for it in items]
        except Exception:
            matrix = None
    if not matrix or len(matrix) != len(items):
        return {"total": len(items), "error": "embed_failed"}

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    def norm(a):
        return sum(x * x for x in a) ** 0.5

    cands = []
    th = body.candidate_threshold
    for i in range(len(items)):
        ni = norm(matrix[i]) or 1.0
        for j in range(i + 1, len(items)):
            nj = norm(matrix[j]) or 1.0
            sim = dot(matrix[i], matrix[j]) / (ni * nj)
            if sim >= th:
                cands.append((round(sim, 4), i, j))
    cands.sort(reverse=True)
    cands = cands[: body.max_candidates]

    if not cands:
        return {"total": len(items), "candidates": 0, "groups": [], "deleted": [], "dry_run": body.dry_run}

    # ---- 2) 分批让模型逐对判定 ----
    verdicts, errors = [], []
    for start in range(0, len(cands), 40):
        chunk = cands[start:start + 40]
        lines = "\n".join(
            f"{k}. A: {items[i]['memory']}\n   B: {items[j]['memory']}"
            for k, (_sim, i, j) in enumerate(chunk)
        )
        prompt = (
            "判断下面每一对句子是不是**同一个事实的两种说法**（只是措辞不同或详略不同）。\n"
            "判定为同一事实的条件：主语、对象、结论完全一致；一条只是把另一条说得更完整也算。\n"
            "以下情况一律判 false：主题相同但说的是不同方面的要求；观点相反；时间/数量/对象不同；"
            "一条是要求、另一条是结果或状态。\n"
            "严格输出 JSON：{\"pairs\": [{\"k\": 编号, \"same\": true/false}]}，每对都要给结论。\n\n"
            f"{lines}"
        )
        try:
            data = _llm_json(prompt, timeout=180)
        except Exception as e:
            errors.append({"stage": "llm", "error": str(e)})
            break
        pairs = data.get("pairs") if isinstance(data, dict) else None
        if not isinstance(pairs, list):
            errors.append({"stage": "parse", "raw": str(data)[:200]})
            continue
        for p_ in pairs:
            if not isinstance(p_, dict):
                continue
            k = p_.get("k")
            if type(k) is not int or not (0 <= k < len(chunk)):
                continue
            if p_.get("same") is not True:
                continue
            verdicts.append(chunk[k])

    # ---- 3) 执行删除：保留信息更完整的一条 ----
    groups, deleted = [], []
    used = set()
    for sim, i, j in verdicts:
        if i in used or j in used:
            continue
        a, b = items[i], items[j]
        loser, keeper = (a, b) if len(a["memory"]) < len(b["memory"]) else (b, a)
        entry = {"keep": keeper["memory"], "drop": loser["memory"], "score": sim}
        if body.dry_run:
            groups.append(entry)
            used.update({i, j})
            continue
        try:
            m.delete(loser["id"])
            deleted.append({"id": loser["id"], "memory": loser["memory"], "kept": keeper["memory"], "score": sim})
            groups.append(entry)
            used.update({i, j})
        except Exception as e:
            errors.append({"stage": "delete", "id": loser["id"], "error": str(e)})

    return {"total": len(items), "candidates": len(cands), "groups": groups,
            "deleted": deleted, "errors": errors, "dry_run": body.dry_run}




# ============ 主题图（借 A-MEM 的 Note 模型 + MemGPT 的分层）============
# 设计来源：
#   A-MEM (agiresearch/A-mem) MemoryNote：content/keywords/tags/context/links/evolution_history
#   MemGPT/Letta：core memory（常驻）+ archival memory（归档），sleep-time 整理
# 与旧实现的区别：主题是**持久节点**，数量由内容决定，名字不再每晚重排。

TOPICS_PATH = os.path.join(BASE, "topics.json")
VECTORS_PATH = os.path.join(BASE, "fact_vectors.json")


def _load_json(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, path)


def _load_topics():
    return _load_json(TOPICS_PATH, {"version": 1, "topics": [], "files": []})


def _cos(a, b):
    import math
    if not a or not b or len(a) != len(b):
        return 0.0
    da = sum(x * x for x in a) ** 0.5 or 1.0
    db = sum(x * x for x in b) ** 0.5 or 1.0
    return sum(x * y for x, y in zip(a, b)) / (da * db)


def _centroid(vectors):
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            out[i] += x
    n = len(vectors)
    return [x / n for x in out]


def _fact_vectors(facts):
    """取事实向量；缺的用 embedding 批量补齐并落盘缓存。"""
    cache = _load_json(VECTORS_PATH, {})
    missing = [f for f in facts if f["id"] not in cache]
    if missing:
        try:
            vs = _embed_batch([f["memory"] for f in missing])
            for f, v in zip(missing, vs):
                cache[f["id"]] = v
            _save_json(VECTORS_PATH, cache)
        except Exception as e:
            logger.warning("fact_vectors 补齐失败：%s", e)
    return {f["id"]: cache.get(f["id"], []) for f in facts}


class TopicSyncIn(BaseModel):
    assign_threshold: float = Field(default=0.60, ge=0.3, le=0.95)
    cluster_threshold: float = Field(default=0.74, ge=0.5, le=0.95)
    merge_threshold: float = Field(default=0.90, ge=0.6, le=0.99)
    archive_days: int = Field(default=60, ge=7, le=3650)
    dry_run: bool = False


@app.post("/topics/sync")
def topics_sync(body: TopicSyncIn):
    """主题图增量同步：新事实用一次 LLM 调用归入已有主题，或提出新主题。

    选题思路来自 A-MEM（笔记有 keywords/tags/links/evolution）与 MemGPT 的分层
    （core=画像常驻，archival=历史归档），主题**数量由内容决定**、名字保持稳定。
    """
    m = mem()
    r = m.get_all(filters={"user_id": USER}, top_k=100000)
    facts = [it for it in (r.get("results") if isinstance(r, dict) else r or [])
             if isinstance(it.get("memory"), str) and it["memory"].strip()]
    store = _load_topics()
    topics = store["topics"]
    now = datetime.datetime.now(TZ).isoformat(timespec="seconds")
    alive = {f["id"] for f in facts}
    for t in topics:
        t["fact_ids"] = [fid for fid in t.get("fact_ids", []) if fid in alive]

    assigned = {fid for t in topics for fid in t["fact_ids"]}
    new_facts = [f for f in facts if f["id"] not in assigned]
    if not facts:
        return {"facts": 0, "topics": len(topics), "new": [], "merged": [], "archived": []}

    # ---- 1) 让模型做归类（一次调用）----
    existing = [t for t in topics]
    lines = []
    for idx, f in enumerate(new_facts):
        lines.append(f"N{idx}. {f['memory'][:120]}")
    topic_lines = "\n".join(f"T{i}. {t.get('name')}：{(t.get('summary') or '')[:60]}" for i, t in enumerate(existing))

    if existing:
        prompt = (
            "下面是一份长期记忆库。第一部分是已有主题（编号 T 开头），第二部分是**尚未归类的新事实**（编号 N 开头）。\n"
            "请把每条新事实分配到最合适的已有主题；如果确实不属于任何已有主题，就为该事实新建一个主题（给出主题名与一句话摘要）。\n"
            "同一批新事实如果属于同一主题，应当新建**同一个**主题。主题名 4-12 字，概括性强。\n"
            "严格输出 JSON：{\"assign\": [{\"n\": 编号, \"t\": 主题编号}], "
            "\"new_topics\": [{\"name\": \"...\", \"summary\": \"...\", \"ns\": [编号, ...]}]}。"
            "assign 里只放能归入已有主题的；new_topics 里放新建的。不要遗漏任何 N。\n\n"
            f"已有主题：\n{topic_lines}\n\n新事实：\n" + "\n".join(lines)
        )
    else:
        prompt = (
            "下面是一份长期记忆的事实列表。请把它们归纳成若干主题（数量由内容自然决定，不要强行凑数，"
            "一般 6~15 个；互不相关的事实各自成主题）。每个主题给一个 4-12 字的名字和一句话摘要。\n"
            "严格输出 JSON：{\"topics\": [{\"name\": \"...\", \"summary\": \"...\", \"ns\": [编号, ...]}]}，"
            "每个编号必须且只能出现一次。\n\n事实：\n" + "\n".join(lines)
        )

    try:
        data = _llm_json(prompt, timeout=240)
    except Exception as e:
        return {"error": "llm_failed", "detail": str(e), "facts": len(facts), "topics": len(topics)}

    idx_map = {i: f["id"] for i, f in enumerate(new_facts)}
    created, merged = [], []
    if isinstance(data, dict):
        for a in (data.get("assign") or []):
            if not isinstance(a, dict):
                continue
            n, t = a.get("n"), a.get("t")
            if type(n) is not int or type(t) is not int or n not in idx_map or not (0 <= t < len(existing)):
                continue
            if idx_map[n] not in existing[t]["fact_ids"]:
                existing[t]["fact_ids"].append(idx_map[n])
                existing[t]["updated_at"] = now
        for nt in (data.get("new_topics") or []):
            if not isinstance(nt, dict) or not isinstance(nt.get("name"), str):
                continue
            ns = [n for n in (nt.get("ns") or []) if type(n) is int and n in idx_map]
            if not ns:
                continue
            created.append({"id": str(uuid.uuid4()), "name": nt["name"].strip()[:24] or "未命名主题",
                            "summary": str(nt.get("summary") or "").strip()[:300], "keywords": [], "tags": [],
                            "centroid": [], "fact_ids": list(dict.fromkeys(idx_map[n] for n in ns)),
                            "pinned": False, "created_at": now, "updated_at": now,
                            "evolution_history": [{"at": now, "op": "auto_create"}]})
        if not existing:
            for nt in (data.get("topics") or []):
                if not isinstance(nt, dict) or not isinstance(nt.get("name"), str):
                    continue
                ns = [n for n in (nt.get("ns") or []) if type(n) is int and n in idx_map]
                if not ns:
                    continue
                created.append({"id": str(uuid.uuid4()), "name": nt["name"].strip()[:24] or "未命名主题",
                                "summary": str(nt.get("summary") or "").strip()[:300], "keywords": [], "tags": [],
                                "centroid": [], "fact_ids": list(dict.fromkeys(idx_map[n] for n in ns)),
                                "pinned": False, "created_at": now, "updated_at": now,
                                "evolution_history": [{"at": now, "op": "bootstrap"}]})
    topics.extend(created)

    # 未归类的漏网事实：并入「其他」
    covered = {fid for t in topics for fid in t["fact_ids"]}
    leftovers = [fid for fid in alive if fid not in covered]
    if leftovers:
        other = next((t for t in topics if t.get("name") == "其他"), None)
        if other is None:
            other = {"id": str(uuid.uuid4()), "name": "其他", "summary": "暂未归类的零散事实",
                     "keywords": [], "tags": [], "centroid": [], "fact_ids": [],
                     "pinned": False, "created_at": now, "updated_at": now,
                     "evolution_history": [{"at": now, "op": "auto_create"}]}
            topics.append(other)
        other["fact_ids"].extend(leftovers)
        other["updated_at"] = now

    # ---- 2) 归档长期很小且不更新的自动主题 ----
    archived = []
    cutoff = datetime.datetime.now(TZ) - datetime.timedelta(days=body.archive_days)
    keep = []
    for t in topics:
        try:
            upd = datetime.datetime.fromisoformat(t.get("updated_at") or now)
        except Exception:
            upd = datetime.datetime.now(TZ)
        if not t.get("pinned") and len(t["fact_ids"]) <= 1 and upd < cutoff:
            archived.append(t["name"])
            continue
        keep.append(t)
    topics = keep

    if body.dry_run:
        return {"facts": len(facts), "topics": len(topics), "new": [t["name"] for t in created],
                "merged": merged, "archived": archived, "dry_run": True,
                "assignment": [{"topic": t.get("name"), "facts": len(t["fact_ids"])} for t in topics]}

    vectors = _fact_vectors(facts)
    for t in topics:
        vs = [vectors[fid] for fid in t.get("fact_ids", []) if vectors.get(fid)]
        t["centroid"] = _centroid(vs) if vs else []
    store["topics"] = topics
    write_cards(topics, {f["id"]: f["memory"] for f in facts})
    _save_json(TOPICS_PATH, store)
    return {"facts": len(facts), "topics": len(topics), "new": [t["name"] for t in created],
            "merged": merged, "archived": archived}


def write_cards(topics, fact_map):
    staging = os.path.join(BASE, "cards.staging")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    files = []
    for t in sorted(topics, key=lambda x: (not x.get("pinned"), -len(x.get("fact_ids", [])))):
        name = str(t.get("name") or "未命名主题")
        slug = "".join(ch for ch in name if ch not in '/\\:*?"<>|').strip()[:40] or "topic"
        body = [f"# {name}", ""]
        if t.get("summary"):
            body += [t["summary"], ""]
        body += ["## 事实", ""]
        for fid in t.get("fact_ids", []):
            text = fact_map.get(fid)
            if text:
                body.append(f"- {text}")
        body += ["", f"_更新：{t.get('updated_at','')}{'　（手动主题）' if t.get('pinned') else ''}_", ""]
        fname = slug + ".md"
        open(os.path.join(staging, fname), "w").write("\n".join(body))
        files.append(fname)
    # L3 画像：取前 8 个主题的一句话摘要
    digest = "\n".join(f"- {t.get('name')}：{t.get('summary','')}" for t in topics[:8] if t.get("summary"))
    profile = f"# 用户画像（自动生成）\n\n更新时间：{datetime.datetime.now(TZ).isoformat(timespec='seconds')}\n\n{digest}\n"
    open(os.path.join(staging, "profile.md"), "w").write(profile)
    files.append("profile.md")
    backup = os.path.join(BASE, "cards.prev")
    shutil.rmtree(backup, ignore_errors=True)
    if os.path.isdir(CARDS):
        os.replace(CARDS, backup)
    os.replace(staging, CARDS)
    shutil.rmtree(backup, ignore_errors=True)
    return files


class TopicAddIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    summary: str = ""
    fact_ids: List[str] = Field(default_factory=list, max_length=50)


@app.get("/topics/list")
def topics_list():
    store = _load_topics()
    return {"topics": [{"id": t["id"], "name": t.get("name"), "summary": t.get("summary", ""),
                        "facts": len(t.get("fact_ids", [])), "pinned": bool(t.get("pinned")),
                        "updated_at": t.get("updated_at")} for t in store["topics"]]}


@app.post("/topics/add")
def topics_add(body: TopicAddIn):
    store = _load_topics()
    now = datetime.datetime.now(TZ).isoformat(timespec="seconds")
    t = {"id": str(uuid.uuid4()), "name": body.name.strip(), "summary": body.summary.strip(),
         "keywords": [], "tags": [], "centroid": [], "fact_ids": list(dict.fromkeys(body.fact_ids)),
         "pinned": True, "created_at": now, "updated_at": now,
         "evolution_history": [{"at": now, "op": "manual_create"}]}
    store["topics"].append(t)
    _save_json(TOPICS_PATH, store)
    r = mem().get_all(filters={"user_id": USER}, top_k=100000)
    items = r.get("results") if isinstance(r, dict) else r or []
    write_cards(store["topics"], {it["id"]: it["memory"] for it in items})
    return {"ok": True, "id": t["id"], "name": t["name"]}




# ============ 快照 / 撤销 / 状态 / 批量操作（借鉴 Apricity 的「破坏性操作先快照」）============
import glob

SNAP_DIR = os.path.join(BASE, "snapshots")


def _snapshot(op: str):
    """把当前完整记忆 + 主题存一份快照，返回文件名。任何破坏性操作前调用。"""
    os.makedirs(SNAP_DIR, exist_ok=True)
    ts = datetime.datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(SNAP_DIR, f"{ts}-{op}.json")
    try:
        r = mem().get_all(filters={"user_id": USER}, top_k=100000)
        items = r.get("results") if isinstance(r, dict) else r or []
        data = {"at": datetime.datetime.now(TZ).isoformat(timespec="seconds"), "op": op,
                "memories": [{"id": it.get("id"), "memory": it.get("memory"),
                              "created_at": it.get("created_at"), "updated_at": it.get("updated_at")} for it in items],
                "topics": _load_topics()}
        tmp = path + ".tmp"
        json.dump(data, open(tmp, "w"), ensure_ascii=False)
        os.replace(tmp, path)
        # 只留最近 20 份
        files = sorted(glob.glob(os.path.join(SNAP_DIR, "*.json")))
        for old in files[:-20]:
            try: os.remove(old)
            except Exception: pass
        return os.path.basename(path)
    except Exception as e:
        logger.warning("快照失败：%s", e)
        return None


@app.get("/snapshots/list")
def snapshots_list():
    os.makedirs(SNAP_DIR, exist_ok=True)
    out = []
    for f in sorted(glob.glob(os.path.join(SNAP_DIR, "*.json")), reverse=True)[:20]:
        try:
            d = json.load(open(f))
            out.append({"file": os.path.basename(f), "at": d.get("at"), "op": d.get("op"),
                        "memories": len(d.get("memories") or [])})
        except Exception:
            pass
    return {"snapshots": out}


class RestoreIn(BaseModel):
    file: str = Field(min_length=1, max_length=200)


@app.post("/snapshots/restore")
def snapshots_restore(body: RestoreIn):
    """把记忆与主题恢复到某份快照（先给当前状态再存一份，避免恢复本身不可撤销）。"""
    name = os.path.basename(body.file)
    path = os.path.join(SNAP_DIR, name)
    if not os.path.isfile(path):
        return {"ok": False, "error": "not found"}
    data = json.load(open(path))
    _snapshot("before-restore")
    m = mem()
    r = m.get_all(filters={"user_id": USER}, top_k=100000)
    current = r.get("results") if isinstance(r, dict) else r or []
    want = {(x.get("memory") or "").strip() for x in (data.get("memories") or [])}
    have = {(x.get("memory") or "").strip() for x in current}
    with _write_lock:
        removed = 0
        for x in current:
            if (x.get("memory") or "").strip() not in want:
                try:
                    m.delete(x["id"]); removed += 1
                except Exception:
                    pass
        added = 0
        for txt in want - have:
            if txt:
                try:
                    m._create_memory(txt, {}, metadata={"user_id": USER}); added += 1
                except Exception:
                    pass
    if isinstance(data.get("topics"), dict):
        _save_json(TOPICS_PATH, data["topics"])
        try:
            rr = m.get_all(filters={"user_id": USER}, top_k=100000)
            items = rr.get("results") if isinstance(rr, dict) else rr or []
            write_cards(data["topics"].get("topics", []), {it["id"]: it["memory"] for it in items})
        except Exception:
            pass
    return {"ok": True, "restored": name, "added": added, "removed": removed}


@app.get("/status")
def status():
    """面板状态卡：数量、上次整理、下次整理、模型。"""
    m = mem()
    r = m.get_all(filters={"user_id": USER}, top_k=100000)
    items = r.get("results") if isinstance(r, dict) else r or []
    store = _load_topics()
    cards = glob.glob(os.path.join(CARDS, "*.md"))
    last = max((os.path.getmtime(f) for f in cards), default=0)
    cfg = json.load(open(CFG))
    sync_log = os.path.join(BASE, "sync.log")
    last_sync = ""
    if os.path.isfile(sync_log):
        lines = [l for l in open(sync_log).read().splitlines() if l.strip()]
        last_sync = lines[-1] if lines else ""
    return {
        "memories": len(items),
        "topics": len(store.get("topics", [])),
        "cards": len(cards),
        "last_card_at": datetime.datetime.fromtimestamp(last, TZ).isoformat(timespec="seconds") if last else "",
        "next_run": "03:30 (Asia/Shanghai)",
        "model": cfg.get("llm", {}).get("config", {}).get("model", ""),
        "embedder": cfg.get("embedder", {}).get("config", {}).get("model", ""),
        "last_sync": last_sync,
        "snapshots": len(glob.glob(os.path.join(SNAP_DIR, "*.json"))),
    }


@app.post("/nightly/run")
def nightly_run():
    """手动触发一次夜间整理（与插件凌晨跑的同一套顺序）。"""
    steps = {}
    steps["snapshot"] = _snapshot("manual-nightly")
    try:
        r = mem().get_all(filters={"user_id": USER}, top_k=100000)
        items = r.get("results") if isinstance(r, dict) else r or []
        steps["consolidate"] = {"before": len(items)}
    except Exception as e:
        steps["consolidate"] = {"error": str(e)}
    try:
        mg = merge_duplicates(MergeIn(dry_run=False))
        steps["merge_duplicates"] = {"deleted": len(mg.get("deleted") or []), "groups": len(mg.get("groups") or [])}
    except Exception as e:
        steps["merge_duplicates"] = {"error": str(e)}
    try:
        sp = supersede(SupersedeIn(dry_run=False))
        steps["supersede"] = {"applied": len(sp.get("applied") or [])}
    except Exception as e:
        steps["supersede"] = {"error": str(e)}
    try:
        ts = topics_sync(TopicSyncIn(dry_run=False))
        steps["topics"] = {"topics": ts.get("topics"), "new": ts.get("new")}
    except Exception as e:
        steps["topics"] = {"error": str(e)}
    try:
        steps["sync"] = sync()
    except Exception as e:
        steps["sync"] = {"error": str(e)}
    return {"ok": True, "steps": steps}


class BulkDeleteIn(BaseModel):
    ids: List[str] = Field(default_factory=list, max_length=500)


@app.post("/memories/bulk_delete")
def memories_bulk_delete(body: BulkDeleteIn):
    if not body.ids:
        return {"ok": True, "deleted": 0}
    snap = _snapshot("bulk-delete")
    m = mem()
    deleted, errors = 0, []
    with _write_lock:
        for mid in body.ids:
            try:
                m.delete(mid); deleted += 1
            except Exception as e:
                errors.append({"id": mid, "error": str(e)})
    return {"ok": True, "deleted": deleted, "errors": errors, "snapshot": snap}


class MergeMemoriesIn(BaseModel):
    ids: List[str] = Field(default_factory=list, min_length=2, max_length=50)


@app.post("/memories/merge")
def memories_merge(body: MergeMemoriesIn):
    """把若干条记忆合并成一条（用模型改写），保留最新的时间戳。"""
    m = mem()
    r = m.get_all(filters={"user_id": USER}, top_k=100000)
    items = {it["id"]: it for it in (r.get("results") if isinstance(r, dict) else r or [])}
    chosen = [items[i] for i in body.ids if i in items]
    if len(chosen) < 2:
        return {"ok": False, "error": "不足两条有效记忆"}
    snap = _snapshot("merge-memories")
    prompt = (
        "把下面几条记忆合并成**一条**更准确、完整的事实陈述（简体中文，单句，不丢关键信息，"
        "不要用「他/这个」指代）。只输出合并后的一句话，不要解释。\n\n"
        + "\n".join(f"- {x['memory']}" for x in chosen)
    )
    try:
        import httpx
        cfg = json.load(open(CFG))
        key = cfg["llm"]["config"]["api_key"]
        base = cfg["llm"]["config"].get("openai_base_url", "https://api.deepseek.com/v1")
        model = cfg["llm"]["config"]["model"]
        rr = httpx.post(f"{base}/chat/completions", timeout=120,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0})
        rr.raise_for_status()
        merged_text = (rr.json()["choices"][0]["message"]["content"] or "").strip().splitlines()[0][:500]
    except Exception as e:
        return {"ok": False, "error": "llm_failed: " + str(e)}
    if not merged_text:
        return {"ok": False, "error": "empty merge result"}
    with _write_lock:
        try:
            m._create_memory(merged_text, {}, metadata={"user_id": USER})
            for x in chosen:
                m.delete(x["id"])
        except Exception as e:
            return {"ok": False, "error": str(e), "snapshot": snap}
    return {"ok": True, "merged": merged_text, "removed": len(chosen), "snapshot": snap}


@app.get("/topics/graph")
def topics_graph(min_sim: float = 0.78, max_links: int = 200):
    """主题图数据：节点 = 主题，边 = 主题中心向量的余弦相似度（现算，不依赖缓存字段）。"""
    store = _load_topics()
    topics = store.get("topics", [])
    vectors = _load_json(VECTORS_PATH, {})
    nodes = []
    centroids = {}
    for t in topics:
        ids = [fid for fid in t.get("fact_ids", []) if fid in vectors]
        vecs = [vectors[fid] for fid in ids]
        c = _centroid(vecs) if vecs else (t.get("centroid") or [])
        centroids[t["id"]] = c
        nodes.append({"id": t["id"], "name": t.get("name"), "facts": len(t.get("fact_ids", [])),
                      "pinned": bool(t.get("pinned"))})
    links = []
    for i in range(len(topics)):
        for j in range(i + 1, len(topics)):
            ci, cj = centroids[topics[i]["id"]], centroids[topics[j]["id"]]
            if ci and cj:
                sim = _cos(ci, cj)
                if sim >= min_sim:
                    links.append({"source": topics[i]["id"], "target": topics[j]["id"], "weight": round(sim, 3)})
    links.sort(key=lambda x: -x["weight"])
    return {"nodes": nodes, "links": links[:max_links], "threshold": min_sim}


class CardsIn(BaseModel):
    max_topics: int = Field(default=8, ge=1, le=20)


@app.post("/cards/generate")
def cards_generate(body: CardsIn):
    """把原子事实聚合成主题卡（L2），再汇总出画像（L3）。"""
    os.makedirs(CARDS, exist_ok=True)
    m = mem()
    r = m.get_all(filters={"user_id": USER}, top_k=100000)
    items = [x for x in (r.get("results") if isinstance(r, dict) else (r or [])) if x.get("memory")]
    if not items:
        return {"topics": 0, "files": []}

    listing = "\n".join(f"{i}. {x['memory']}" for i, x in enumerate(items))
    prompt = (
        "下面是一个用户的长期记忆事实列表。请把它们按主题聚合成不超过 "
        f"{body.max_topics} 个主题卡。\n"
        '只输出 JSON：{"topics":[{"name":"主题名(<=12字)","summary":"2-4句中文概述","facts":[事实编号]}]}\n'
        "要求：每个事实最多归入一个主题；主题名用名词短语；summary 要写出结论，不要复述原文。\n\n"
        + listing
    )
    data = _llm_json(prompt)
    topics = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(topics, list):
        return {"topics": 0, "files": [], "error": "LLM 返回结构非法"}

    # 严格校验：主题名/摘要为字符串、facts 为合法不重复索引（P1-18）
    clean, used_facts, used_slug = [], set(), set()
    for t in topics:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        summary = t.get("summary")
        if not isinstance(name, str) or not name.strip() or not isinstance(summary, str):
            continue
        slug = "".join(ch for ch in name.strip() if ch not in '/\\:*?"<>|').strip()
        if not slug or slug.lower() == "profile" or slug in used_slug:
            continue
        used_slug.add(slug)
        raw_facts = t.get("facts")
        if not isinstance(raw_facts, list):
            continue
        facts = []
        for i in raw_facts:
            if type(i) is not int or not (0 <= i < len(items)) or i in used_facts:
                continue
            used_facts.add(i)
            facts.append(items[i]["memory"])
        clean.append({"name": name.strip(), "slug": slug, "summary": summary.strip(), "facts": facts})
    if not clean:
        return {"topics": 0, "files": [], "error": "没有通过校验的主题"}

    # 先写临时目录再整体切换（P1-15）
    staging = os.path.join(BASE, "cards.staging")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    files = []
    for t in clean:
        body_md = [f"# {t['name']}", "", t["summary"], "", "## 事实", ""]
        body_md += [f"- {f}" for f in t["facts"]] if t["facts"] else ["- （无）"]
        fname = t["slug"] + ".md"
        open(os.path.join(staging, fname), "w").write("\n".join(body_md) + "\n")
        files.append(fname)
    digest = "\n".join(f"- {t['name']}: {t['summary']}" for t in clean)
    profile = f"# 用户画像（自动生成）\n\n更新时间：{datetime.datetime.now(TZ).isoformat(timespec='seconds')}\n\n{digest}\n"
    open(os.path.join(staging, "profile.md"), "w").write(profile)
    files.append("profile.md")

    backup = os.path.join(BASE, "cards.prev")
    shutil.rmtree(backup, ignore_errors=True)
    if os.path.isdir(CARDS):
        os.replace(CARDS, backup)
    os.replace(staging, CARDS)
    shutil.rmtree(backup, ignore_errors=True)   # 发布成功后清掉上一版（P1-15）
    return {"topics": len(clean), "files": files}


@app.get("/cards/list")
def cards_list():
    if not os.path.isdir(CARDS):
        return {"files": []}
    out = []
    for f in sorted(os.listdir(CARDS)):
        if f.endswith(".md"):
            out.append({"name": f, "size": os.path.getsize(os.path.join(CARDS, f))})
    return {"files": out}


@app.get("/cards/read")
def cards_read(name: str):
    import pathlib
    root = pathlib.Path(CARDS).resolve()
    p = (root / name).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return {"error": "not found"}
    if p.parent != root or not p.is_file() or p.suffix != ".md":
        return {"error": "not found"}
    return {"name": name, "content": p.read_text(encoding="utf-8")}
