/**
 * dsh-mem0 —— 设置页「记忆」面板（Client 半边）。
 * 布局参考 dsh-mnemon 的「记忆系统」页：页面头 + 区块头 + 卡片；
 * 图谱带缩放平移与图例。数据走 /mem0/*。
 */
window.__ModuleLoader__.load({
  id: 'dsh-mem0',
  factory: (require) => {
    const React = require('react');
    const e = React.createElement;
    const { useState, useEffect, useCallback, useRef, useMemo } = React;

    /** 极简全局状态（侧边栏按钮与全屏页是两个独立挂载点，需要共享开关）。 */
    const pageStore = {
      open: false,
      subs: new Set(),
      set(v) { this.open = v; this.subs.forEach((f) => f(v)); },
      toggle() { this.set(!this.open); },
      subscribe(f) { this.subs.add(f); return () => this.subs.delete(f); },
    };

    const API = '/mem0';
    const h = (path, opt) => fetch(API + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opt || {})).then((r) => r.json());

    const C = {
      base: 'var(--dsw-alias-bg-base)',
      l1: 'var(--dsw-alias-bg-layer-1)',
      l2: 'var(--dsw-alias-bg-layer-2)',
      l3: 'var(--dsw-alias-bg-layer-3)',
      t1: 'var(--dsw-alias-label-primary)',
      t2: 'var(--dsw-alias-label-secondary)',
      t3: 'var(--dsw-alias-label-tertiary)',
      cap: 'var(--dsw-alias-label-caption)',
      b1: 'var(--dsw-alias-border-l1)',
      b2: 'var(--dsw-alias-border-l2)',
      b3: 'var(--dsw-alias-border-l3)',
      brand: 'var(--dsw-alias-brand-primary)',
      ok: 'var(--dsw-alias-state-success-primary)',
      warn: 'var(--dsw-alias-state-warn-primary)',
      err: 'var(--dsw-alias-state-error-primary)',
      inv: 'var(--dsw-alias-label-primary-inverted)',
      hover: 'var(--dsw-alias-interactive-bg-hover)',
    };
    const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
    const NUM = { fontVariantNumeric: 'tabular-nums lining-nums' };
    const T = { fast: '120ms ease', mid: '160ms ease' };

    /** 观测**容器**宽度：设置页内容区约 564px，不能用 window.innerWidth 判断。 */
    function useContainerWidth(ref) {
      const [w, setW] = useState(640);
      useEffect(() => {
        const el = ref.current;
        if (!el) return undefined;
        const read = () => setW(el.clientWidth || 640);
        read();
        if (typeof ResizeObserver === 'function') {
          const ro = new ResizeObserver(read);
          ro.observe(el);
          return () => ro.disconnect();
        }
        window.addEventListener('resize', read);
        return () => window.removeEventListener('resize', read);
      }, [ref]);
      return w;
    }

    /** 力导向布局：斥力 + 弹簧 + 向心，迭代收敛；碰撞半径留白 */
    function forceLayout(nodes, links, w, hgt, ticks) {
      const n = nodes.length || 1;
      const idx = new Map(nodes.map((d, i) => [d.id, i]));
      const pos = nodes.map((d, i) => {
        const ang = (i / n) * Math.PI * 2;
        const rad = Math.min(w, hgt) * 0.3;
        return { x: w / 2 + Math.cos(ang) * rad, y: hgt / 2 + Math.sin(ang) * rad, vx: 0, vy: 0, r: 8 + 3 * Math.sqrt(d.facts || 1) };
      });
      pos.forEach((p) => { p.r = Math.max(12, Math.min(32, p.r)); });
      const edges = (links || []).map((l) => [idx.get(l.source), idx.get(l.target), l.weight || 0]).filter((x) => x[0] != null && x[1] != null);
      const iterations = ticks || 280;
      for (let t = 0; t < iterations; t += 1) {
        for (let i = 0; i < n; i += 1) {
          for (let j = i + 1; j < n; j += 1) {
            const dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
            const d2 = dx * dx + dy * dy || 1;
            const d = Math.sqrt(d2);
            const f = (60 * 60) / d2;
            const fx = (dx / d) * f, fy = (dy / d) * f;
            pos[i].vx += fx; pos[i].vy += fy; pos[j].vx -= fx; pos[j].vy -= fy;
            const minGap = pos[i].r + pos[j].r + 24;
            if (d < minGap) {
              const push = (minGap - d) * 0.5;
              pos[i].vx += (dx / d) * push * 0.4; pos[i].vy += (dy / d) * push * 0.4;
              pos[j].vx -= (dx / d) * push * 0.4; pos[j].vy -= (dy / d) * push * 0.4;
            }
          }
        }
        edges.forEach(([a, b, wt]) => {
          const ideal = 192 - 96 * wt;
          const dx = pos[b].x - pos[a].x, dy = pos[b].y - pos[a].y;
          const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const f = (d - ideal) * 0.012;
          const fx = (dx / d) * f, fy = (dy / d) * f;
          pos[a].vx += fx; pos[a].vy += fy; pos[b].vx -= fx; pos[b].vy -= fy;
        });
        for (let i = 0; i < n; i += 1) {
          pos[i].vx += (w / 2 - pos[i].x) * 0.0015;
          pos[i].vy += (hgt / 2 - pos[i].y) * 0.0015;
          pos[i].vx *= 0.62; pos[i].vy *= 0.62;
          pos[i].x = Math.max(48 + pos[i].r, Math.min(w - 48 - pos[i].r, pos[i].x + pos[i].vx));
          pos[i].y = Math.max(48 + pos[i].r, Math.min(hgt - 48 - pos[i].r, pos[i].y + pos[i].vy));
        }
      }
      return pos;
    }

    /** 线性 SVG 图标（描边跟随 currentColor，尺寸 14）。 */
    function Icon(props) {
      const size = (props && props.size) || 14;
      const paths = {
        refresh: ['M3.5 8a4.5 4.5 0 0 1 7.7-3.2', 'M11.5 2.6v2.6H8.9', 'M12.5 8a4.5 4.5 0 0 1-7.7 3.2', 'M4.5 13.4v-2.6h2.6'],
        undo: ['M4 6.5h5.2a3.3 3.3 0 0 1 0 6.6H6', 'M6.2 3.8 3.5 6.5l2.7 2.7'],
        sync: ['M3.2 8a4.8 4.8 0 0 1 8.1-3.5', 'M12.8 8a4.8 4.8 0 0 1-8.1 3.5', 'M11.6 2.4v2.9H8.7', 'M4.4 13.6v-2.9h2.9'],
        plus: ['M8 3.4v9.2', 'M3.4 8h9.2'],
        pencil: ['M3.6 12.4l.4-2.2 6.2-6.2 1.8 1.8-6.2 6.2-2.2.4z'],
        trash: ['M3.4 4.6h9.2', 'M6.4 4.6V3.4h3.2v1.2', 'M5 4.6l.5 8h5l.5-8'],
        close: ['M4 4l8 8', 'M12 4l-8 8'],
        search: ['M7.2 11.6a4.4 4.4 0 1 0 0-8.8 4.4 4.4 0 0 0 0 8.8z', 'M10.6 10.6l2.8 2.8'],
      };
      return React.createElement('svg', {
        width: size, height: size, viewBox: '0 0 16 16', fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round',
        style: { flexShrink: 0, display: 'block' }, 'aria-hidden': true,
      }, (paths[props && props.name] || []).map((d, i) => React.createElement('path', { key: i, d })));
    }

    function Spinner() {
      return e('span', {
        style: { display: 'inline-block', width: 14, height: 14, borderRadius: '50%', border: '2px solid ' + C.b3, borderTopColor: C.t2, animation: 'mem0spin 800ms linear infinite' },
      });
    }

    function Panel(props) {
      const full = props && props.full === true;
      const rootRef = useRef(null);
      const cw = useContainerWidth(rootRef);
      const small = cw < 620;
      const pad = 0;

      const [tab, setTab] = useState('mem');
      const [items, setItems] = useState([]);
      const [status, setStatus] = useState(null);
      const [q, setQ] = useState('');
      const [addText, setAddText] = useState('');
      const [busy, setBusy] = useState('');
      const [notice, setNotice] = useState(null);
      const [sel, setSel] = useState({});
      const [cards, setCards] = useState([]);
      const [cardBody, setCardBody] = useState('');
      const [activeCard, setActiveCard] = useState('');
      const [graph, setGraph] = useState({ nodes: [], links: [] });
      const [hoverNode, setHoverNode] = useState('');
      const [pinnedNode, setPinnedNode] = useState('');
      const [view, setView] = useState({ k: 1, x: 0, y: 0 });
      const graphAreaRef = useRef(null);
      const [palette, setPalette] = useState(false);
      const [pq, setPq] = useState('');
      const [pIdx, setPIdx] = useState(0);
      const noticeTimer = useRef(null);

      const say = useCallback((msg, kind) => {
        setNotice({ msg, kind: kind || 'info' });
        if (noticeTimer.current) clearTimeout(noticeTimer.current);
        if (!kind || kind === 'ok') noticeTimer.current = setTimeout(() => setNotice(null), 4000);
      }, []);

      const load = useCallback(async () => {
        const [l, st] = await Promise.all([h('/list'), h('/status')]);
        setItems(l.items || []);
        setStatus(st);
      }, []);
      const refreshCards = useCallback(async () => { const r = await h('/cards/list'); setCards(r.files || []); }, []);
      const loadGraph = useCallback(async () => { const g = await h('/topics/graph'); setGraph({ nodes: g.nodes || [], links: g.links || [] }); }, []);
      useEffect(() => { load(); refreshCards(); }, [load, refreshCards]);
      useEffect(() => { if (tab === 'graph') loadGraph(); }, [tab, loadGraph]);

      // 图谱缩放 / 平移：滚轮缩放，按住拖动平移
      useEffect(() => {
        const el = graphAreaRef.current;
        if (!el || tab !== 'graph') return undefined;
        const onWheel = (ev) => {
          ev.preventDefault();
          const factor = ev.deltaY > 0 ? 0.92 : 1.08;
          setView((v) => {
            const k = Math.max(0.45, Math.min(3, v.k * factor));
            const rect = el.getBoundingClientRect();
            const px = ev.clientX - rect.left - rect.width / 2;
            const py = ev.clientY - rect.top - rect.height / 2;
            return { k, x: px - (px - v.x) * (k / v.k), y: py - (py - v.y) * (k / v.k) };
          });
        };
        let dragging = false;
        let sx = 0, sy = 0, ox = 0, oy = 0;
        const onDown = (ev) => {
          if (ev.button !== 0) return;
          dragging = true; sx = ev.clientX; sy = ev.clientY;
          setView((v) => { ox = v.x; oy = v.y; return v; });
          el.style.cursor = 'grabbing';
        };
        const onMove = (ev) => {
          if (!dragging) return;
          setView((v) => ({ k: v.k, x: ox + (ev.clientX - sx), y: oy + (ev.clientY - sy) }));
        };
        const onUp = () => { dragging = false; if (el) el.style.cursor = 'grab'; };
        el.addEventListener('wheel', onWheel, { passive: false });
        el.addEventListener('mousedown', onDown);
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
        el.style.cursor = 'grab';
        return () => {
          el.removeEventListener('wheel', onWheel);
          el.removeEventListener('mousedown', onDown);
          window.removeEventListener('mousemove', onMove);
          window.removeEventListener('mouseup', onUp);
        };
      }, [tab]);

      // ⌘K / Ctrl+K
      useEffect(() => {
        const onKey = (ev) => {
          if ((ev.metaKey || ev.ctrlKey) && (ev.key === 'k' || ev.key === 'K')) { ev.preventDefault(); setPalette((v) => !v); setPq(''); setPIdx(0); }
          else if (ev.key === 'Escape') setPalette(false);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
      }, []);

      const toggle = (id) => setSel((s) => Object.assign({}, s, { [id]: !s[id] }));
      const selIds = useMemo(() => Object.keys(sel).filter((k) => sel[k]), [sel]);
      const paletteList = useMemo(() => {
        const kw = pq.trim();
        return (items || []).filter((x) => !kw || x.memory.includes(kw)).slice(0, 12);
      }, [items, pq]);

      const search = async () => {
        if (!q.trim()) { await load(); return; }
        setBusy('搜索中');
        try { const r = await h('/search', { method: 'POST', body: JSON.stringify({ query: q, limit: 50 }) }); setItems(r.items || []); }
        finally { setBusy(''); }
      };
      const add = async () => {
        if (!addText.trim()) return;
        setBusy('抽取中');
        try { await h('/add', { method: 'POST', body: JSON.stringify({ text: addText }) }); setAddText(''); await load(); say('已新增', 'ok'); }
        finally { setBusy(''); }
      };
      const del = async (id, text) => {
        if (!confirm('删除这条记忆？\n\n' + text + '\n\n（会先存快照，可撤销）')) return;
        await h('/delete', { method: 'POST', body: JSON.stringify({ id }) }); await load(); say('已删除，可点「撤销上次」恢复', 'ok');
      };
      const edit = async (id, text) => {
        const v = prompt('修改这条记忆：', text);
        if (v == null || !v.trim()) return;
        await h('/update', { method: 'POST', body: JSON.stringify({ id, text: v.trim() }) }); await load(); say('已更新', 'ok');
      };
      const bulkDelete = async () => {
        if (!selIds.length) return;
        if (!confirm(`删除选中的 ${selIds.length} 条？（会先存快照）`)) return;
        setBusy('删除中');
        try { const r = await h('/memories/bulk_delete', { method: 'POST', body: JSON.stringify({ ids: selIds }) }); setSel({}); await load(); say(`已删除 ${r.deleted} 条`, 'ok'); }
        finally { setBusy(''); }
      };
      const bulkMerge = async () => {
        if (selIds.length < 2) return;
        if (!confirm(`把选中的 ${selIds.length} 条合并成一条？`)) return;
        setBusy('合并中');
        try { const r = await h('/memories/merge', { method: 'POST', body: JSON.stringify({ ids: selIds }) }); setSel({}); await load(); say(r.ok ? '已合并' : '合并失败：' + (r.error || ''), r.ok ? 'ok' : 'err'); }
        finally { setBusy(''); }
      };
      const runNightly = async () => {
        if (!confirm('现在手动跑一次完整整理？')) return;
        setBusy('整理中');
        try { await h('/nightly/run', { method: 'POST' }); await load(); await refreshCards(); say('整理完成', 'ok'); }
        catch (err) { say('整理失败：' + String(err), 'err'); }
        finally { setBusy(''); }
      };
      const undo = async () => {
        const r0 = await h('/snapshots/list');
        const snaps = r0.snapshots || [];
        if (!snaps.length) { say('没有可用快照', 'warn'); return; }
        const latest = snaps[0];
        if (!confirm(`恢复到 ${latest.at} 的快照？（操作 ${latest.op}，含 ${latest.memories} 条）`)) return;
        const r = await h('/snapshots/restore', { method: 'POST', body: JSON.stringify({ file: latest.file }) });
        await load(); await refreshCards();
        say(r.ok ? `已恢复：+${r.added} / -${r.removed}` : '恢复失败', r.ok ? 'ok' : 'err');
      };
      const sync = async () => {
        setBusy('同步中');
        try { await h('/sync', { method: 'POST' }); await load(); say('已推送 GitHub', 'ok'); }
        finally { setBusy(''); }
      };
      const openCard = async (name) => {
        setActiveCard(name);
        const r = await h('/cards/read?name=' + encodeURIComponent(name));
        setCardBody(r.content || '(空)');
      };

      // ---------- 样式 ----------
      const S = {
        root: Object.assign({ display: 'flex', flexDirection: 'column', gap: 0, color: C.t1, width: '100%', minWidth: 0, paddingBottom: 8, boxSizing: 'border-box', fontFamily: 'inherit' },
          full ? { maxWidth: 1080, margin: '0 auto', padding: '4px 0 24px' } : {}),
        stateArea: { display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12, paddingBottom: 12 },
        titleRow: { display: 'flex', alignItems: 'baseline', gap: 12 },
        title: { fontSize: 20, lineHeight: '28px', fontWeight: 600, margin: 0 },
        count: { fontSize: 13, lineHeight: '20px', color: C.t2, ...NUM },
        metaRow: { display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 8, fontSize: 12, lineHeight: '18px', color: C.t2, ...NUM },
        sep: { color: C.cap },
        actions: { display: 'flex', gap: 8, marginLeft: 'auto', flexShrink: 0 },
        btn: (variant) => Object.assign({
          height: 32, padding: '0 12px', borderRadius: 8, fontSize: 13, lineHeight: '20px', fontWeight: 500, cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', gap: 4, transition: `background ${T.fast}, border-color ${T.fast}, filter ${T.fast}`,
          background: C.l1, border: '1px solid ' + C.b2, color: C.t1,
        }, variant === 'primary' ? { background: C.brand, borderColor: C.brand, color: C.inv, minWidth: 96, fontWeight: 500 } : {},
        variant === 'danger' ? { background: 'transparent', borderColor: C.b2, color: C.err } : {},
        variant === 'ghost' ? { background: 'transparent', border: 0, color: C.t2 } : {}),
        iconBtn: { width: 28, height: 28, borderRadius: 6, border: 0, background: 'transparent', color: C.t3, cursor: 'pointer', fontSize: 13, lineHeight: '28px', padding: 0, transition: `background ${T.fast}, color ${T.fast}` },
        notice: { height: 36, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8, padding: '0 12px', borderRadius: 8, background: C.l1, fontSize: 13, color: C.t1, opacity: notice ? 1 : 0, transition: `opacity ${T.mid}`, pointerEvents: notice ? 'auto' : 'none' },
        tabs: { display: 'flex', gap: 4, borderBottom: '1px solid ' + C.b1, height: 44 },
        tab: (on) => ({ position: 'relative', minWidth: 80, height: 44, padding: '0 12px', border: 0, background: 'transparent', cursor: 'pointer', fontSize: 13, lineHeight: '20px', fontWeight: on ? 600 : 500, color: on ? C.t1 : C.t2, transition: `color ${T.mid}` }),
        tabBar: { position: 'absolute', left: 12, right: 12, bottom: 0, height: 2, background: C.brand, opacity: 1, transition: `opacity ${T.mid}` },
        content: { paddingTop: 16, position: 'relative', display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minHeight: 0 },
        toolbar: { display: 'flex', flexDirection: small ? 'column' : 'row', gap: 8, flexWrap: 'wrap' },
        inputWrap: { position: 'relative', display: 'flex', alignItems: 'center', flex: small ? '1 1 100%' : '1 1 200px', minWidth: 0, height: 40, borderRadius: 8, background: C.l1, border: '1px solid ' + C.b2, transition: `border-color ${T.fast}` },
        inputIcon: { position: 'absolute', left: 12, color: C.cap, fontSize: 13, pointerEvents: 'none' },
        input: { flex: 1, height: '100%', padding: '0 12px 0 34px', border: 0, outline: 'none', background: 'transparent', color: C.t1, fontSize: 14, lineHeight: '22px' },
        inputPlain: { flex: 1, height: '100%', padding: '0 12px', border: 0, outline: 'none', background: 'transparent', color: C.t1, fontSize: 14 },
        inlineBtn: { height: 32, minWidth: 64, marginRight: 4, borderRadius: 8, border: 0, background: C.l2, color: C.t1, fontSize: 13, cursor: 'pointer' },
        list: { background: C.l1, borderRadius: 12, overflowY: 'auto', overflowX: 'hidden', padding: '4px 0', maxHeight: small ? 360 : 420 },
        row: (checked) => ({ display: 'flex', gap: 10, alignItems: 'center', minHeight: 44, padding: '6px 12px', background: checked ? C.l2 : 'transparent', borderBottom: '1px solid ' + C.b1, transition: `background ${T.fast}` }),
        rowTxt: { flex: 1, minWidth: 0, fontSize: 14, lineHeight: '20px', color: C.t1, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' },
        chip: { display: 'inline-flex', alignItems: 'center', height: 20, padding: '0 8px', borderRadius: 10, background: C.l2, border: '1px solid ' + C.b1, fontSize: 12, lineHeight: '16px', color: C.cap, ...NUM },
        bulk: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', minHeight: 44, padding: '4px 8px', borderRadius: 10, background: C.l3, border: '1px solid ' + C.b2 },
        empty: { minHeight: 240, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4, padding: 32, textAlign: 'center' },
        emptyTitle: { fontSize: 16, lineHeight: '24px', fontWeight: 600, color: C.t1 },
        emptyDesc: { fontSize: 13, lineHeight: '20px', color: C.t2 },
        cardBar: { display: 'flex', gap: 8, overflowX: 'auto', height: 40, alignItems: 'center' },
        cardBtn: (on) => ({ flex: '0 0 auto', display: 'inline-flex', alignItems: 'center', gap: 5, height: 32, padding: '0 12px', borderRadius: 6, border: '1px solid ' + (on ? C.b2 : C.b1), background: on ? C.l3 : 'transparent', color: on ? C.t1 : C.t2, fontSize: 12, fontFamily: MONO, cursor: 'pointer', whiteSpace: 'nowrap', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }),
        pre: { flex: 1, margin: 0, padding: small ? 16 : 24, background: C.l1, borderRadius: 12, fontFamily: MONO, fontSize: 13, lineHeight: '22px', color: C.t1, whiteSpace: 'pre-wrap', overflow: 'auto', maxHeight: 420 },
        graphWrap: { position: 'relative', background: C.l1, borderRadius: 12, overflow: 'hidden', display: 'flex', flexDirection: 'column' },
        legend: { minHeight: 48, borderTop: '1px solid ' + C.b1, display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px 18px', padding: '8px 16px', fontSize: 12, lineHeight: '16px', color: C.t2, ...NUM },
        overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,.76)', zIndex: 1000, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', paddingTop: '12vh' },
        palette: { width: 640, maxWidth: 'calc(100vw - 32px)', maxHeight: 'min(70vh, 520px)', display: 'flex', flexDirection: 'column', background: C.l2, border: '1px solid ' + C.b2, borderRadius: 12, overflow: 'hidden', boxShadow: '0 24px 64px rgba(0,0,0,.5)' },
        paletteHead: { height: 56, display: 'flex', alignItems: 'center', gap: 12, padding: '0 16px', borderBottom: '1px solid ' + C.b1 },
        paletteInput: { flex: 1, border: 0, outline: 'none', background: 'transparent', color: C.t1, fontSize: 16, lineHeight: '24px' },
        paletteList: { padding: 8, overflowY: 'auto' },
        paletteRow: (on) => ({ height: 48, display: 'flex', alignItems: 'center', gap: 12, padding: '0 12px', borderRadius: 8, cursor: 'pointer', background: on ? C.l3 : 'transparent', transition: `background ${T.fast}` }),
        paletteTxt: { flex: 1, minWidth: 0, fontSize: 14, lineHeight: '20px', color: C.t1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
        kbd: { fontSize: 12, lineHeight: '16px', color: C.cap, padding: '1px 6px', border: '1px solid ' + C.b1, borderRadius: 5 },
        pageHead: { display: 'flex', flexDirection: 'column', gap: 6, paddingBottom: 14 },
        pageTitle: { fontSize: 18, lineHeight: '26px', fontWeight: 600, margin: 0 },
        pageDesc: { fontSize: 12.5, lineHeight: '18px', color: C.t2 },
        headRow: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' },
        pills: { display: 'flex', gap: 6, flexWrap: 'wrap' },
        pill: { display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 9px', borderRadius: 999, border: '1px solid ' + C.b1, background: C.l1, fontSize: 11.5, lineHeight: '16px', color: C.t2, whiteSpace: 'nowrap', ...NUM },
        pillOn: { borderColor: 'color-mix(in srgb, ' + C.brand + ' 45%, transparent)', color: C.brand },
        pillBtn: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', height: 22, minWidth: 26, padding: '0 8px', borderRadius: 999, border: '1px solid ' + C.b1, background: C.l1, color: C.t2, cursor: 'pointer', fontSize: 12, lineHeight: '16px', fontFamily: 'inherit' },
        sectionHead: { display: 'flex', alignItems: 'flex-end', gap: 12, padding: '18px 0 10px', flexWrap: 'wrap' },
        sectionTitle: { fontSize: 13.5, lineHeight: '20px', fontWeight: 600, margin: 0 },
        sectionDesc: { fontSize: 12, lineHeight: '18px', color: C.t2 },
        cardShell: { background: C.l1, border: '1px solid ' + C.b1, borderRadius: 10, overflow: 'hidden', display: 'flex', flexDirection: 'column' },
        cardBarInner: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderBottom: '1px solid ' + C.b1, flexWrap: 'wrap' },
        cardBody: { padding: '0' },
      };

      // ---------- 顶部状态区 ----------
      const st = status || {};
      const stateArea = e('div', { style: S.pageHead },
        e('div', { style: S.headRow },
          e('h2', { style: S.pageTitle }, '长期记忆'),
          e('div', { style: S.pills },
            e('span', { style: S.pill }, `${st.memories || 0} 条事实`),
            e('span', { style: S.pill }, `${st.topics || 0} 个主题`),
            e('span', { style: S.pill }, `${st.cards || 0} 张卡片`),
            e('span', { style: Object.assign({}, S.pill, st.model ? S.pillOn : {}) }, st.model || '未配置模型'),
          ),
          e('span', { style: { flex: 1 } }),
          e('div', { style: S.actions },
            e('button', { style: Object.assign({}, S.btn('primary'), { gap: 6 }), onClick: runNightly, disabled: busy === '整理中' },
              busy === '整理中' ? e(Spinner) : e(Icon, { name: 'refresh' }), '立即整理'),
            e('button', { style: Object.assign({}, S.btn(), { gap: 5 }), onClick: undo }, e(Icon, { name: 'undo' }), '撤销上次'),
            e('button', { style: Object.assign({}, S.btn(), { gap: 5 }), onClick: sync }, e(Icon, { name: 'sync' }), '同步'),
          ),
        ),
        e('div', { style: S.pageDesc },
          `每轮对话自动召回画像与相关事实；上次整理 ${(st.last_card_at || '').replace('T', ' ').slice(5, 16) || '—'}（凌晨自动，也可手动触发）。`),
      );

      // ---------- 提示区 ----------
      const noticeKind = notice && notice.kind;
      const noticeEl = e('div', { style: Object.assign({}, S.notice, notice && noticeKind === 'err' ? { borderLeft: '2px solid ' + C.err } : notice && noticeKind === 'warn' ? { borderLeft: '2px solid ' + C.warn } : {}) },
        busy && e(Spinner),
        e('span', { style: { flex: 1 } }, busy || (notice ? notice.msg : '')),
        notice && !busy && e('button', { style: S.iconBtn, onClick: () => setNotice(null) }, '×'),
      );

      // ---------- 页签 ----------
      const tabsEl = e('div', { style: S.tabs },
        [['mem', '记忆'], ['card', '主题卡'], ['graph', '主题图']].map(([k, label]) => e('button', {
          key: k, style: S.tab(tab === k), onClick: () => setTab(k),
        }, label, tab === k && e('span', { style: S.tabBar }))),
      );

      // ---------- 记忆页 ----------
      const memTab = e('div', { style: S.content },
        e('div', { style: S.sectionHead },
          e('div', null,
            e('h3', { style: S.sectionTitle }, '记忆条目'),
            e('div', { style: S.sectionDesc }, '按语义检索，可编辑、合并、删除；删除前自动快照'),
          ),
          e('span', { style: { flex: 1 } }),
          e('div', { style: S.pills }, e('span', { style: S.pill }, `当前显示 ${items.length} 条`)),
        ),
        e('div', { style: S.cardShell },
          e('div', { style: S.cardBarInner },
            e('div', { style: S.inputWrap },
              e('span', { style: S.inputIcon }, '⌕'),
              e('input', {
                style: S.input, placeholder: '语义搜索记忆…', value: q,
                onChange: (ev) => setQ(ev.target.value),
                onKeyDown: (ev) => { if (ev.key === 'Enter') search(); },
              }),
            ),
            e('div', { style: S.inputWrap },
              e('input', {
                style: S.inputPlain, placeholder: '新增一条记忆（一句话事实）', value: addText,
                onChange: (ev) => setAddText(ev.target.value),
                onKeyDown: (ev) => { if (ev.key === 'Enter') add(); },
              }),
              e('button', {
                style: Object.assign({}, S.inlineBtn, addText.trim() ? {} : { opacity: 0.4, cursor: 'default' }),
                onClick: add, disabled: !addText.trim(),
              }, '添加'),
            ),
          ),
          e('div', { style: Object.assign({}, S.list, { background: 'transparent', borderRadius: 0, maxHeight: small ? 380 : 560 }) },
            items.map((it) => e('div', {
              key: it.id,
              style: S.row(!!sel[it.id]),
              onMouseEnter: (ev) => { if (!sel[it.id]) ev.currentTarget.style.background = C.hover; },
              onMouseLeave: (ev) => { if (!sel[it.id]) ev.currentTarget.style.background = 'transparent'; },
            },
              e('input', {
                type: 'checkbox', checked: !!sel[it.id], onChange: () => toggle(it.id),
                style: { width: 16, height: 16, margin: 0, accentColor: C.brand, flexShrink: 0 },
              }),
              e('div', { style: S.rowTxt, title: it.memory }, it.memory),
              it.score != null && e('span', { style: S.chip }, '相关度 ' + it.score.toFixed(2)),
              e('div', { style: { display: 'flex', gap: 2, flexShrink: 0 } },
                e('button', { style: Object.assign({}, S.iconBtn, { display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }), title: '编辑', onClick: () => edit(it.id, it.memory) }, e(Icon, { name: 'pencil', size: 13 })),
                e('button', {
                  style: Object.assign({}, S.iconBtn, { display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }), title: '删除',
                  onMouseEnter: (ev) => { ev.currentTarget.style.color = C.err; },
                  onMouseLeave: (ev) => { ev.currentTarget.style.color = C.t3; },
                  onClick: () => del(it.id, it.memory),
                }, e(Icon, { name: 'trash', size: 13 })),
              ),
            )),
            !items.length && e('div', { style: S.empty },
              e('div', { style: S.emptyTitle }, q ? '没有匹配的记忆' : '还没有记忆'),
              e('div', { style: S.emptyDesc }, q ? '换个关键词试试' : '在对话里聊聊，或手动添加第一条'),
              q && e('button', { style: Object.assign({}, S.btn(), { marginTop: 12 }), onClick: () => { setQ(''); load(); } }, '清除搜索'),
            ),
          ),
        ),
        selIds.length > 0 && e('div', { style: S.bulk },
          e('span', { style: { fontSize: 13, color: C.t1, ...NUM } }, `已选 ${selIds.length}`),
          e('span', { style: { width: 1, height: 20, background: C.b2 } }),
          e('button', { style: S.btn('primary'), onClick: bulkMerge }, '合并'),
          e('button', { style: S.btn('danger'), onClick: bulkDelete }, '删除'),
          e('button', { style: S.btn('ghost'), onClick: () => setSel({}) }, '取消'),
        ),
      );

      // ---------- 主题卡页 ----------
      const cardTab = e('div', { style: S.content },
        e('div', { style: S.sectionHead },
          e('div', null,
            e('h3', { style: S.sectionTitle }, '主题卡'),
            e('div', { style: S.sectionDesc }, '由 nightly 整理生成；手动创建的主题标记为 pinned，不会被覆盖'),
          ),
          e('span', { style: { flex: 1 } }),
          e('div', { style: S.pills }, e('span', { style: S.pill }, `${cards.length} 张`)),
        ),
        e('div', { style: S.cardShell },
          e('div', { style: S.cardBarInner },
            e('button', {
              style: S.cardBtn(false),
              onClick: async () => {
                const name = window.prompt('新主题名称（4-12 字）', '');
                if (!name) return;
                const summary = window.prompt('一句话摘要', '') || '';
                const r = await h('/topics/add', { name, summary, fact_ids: [] });
                if (r && r.ok) { await refreshCards(); say('已创建主题：' + r.name, 'ok'); }
              },
            }, e(Icon, { name: 'plus', size: 13 }), '新建主题'),
            cards.map((f) => e('button', {
              key: f.name, style: S.cardBtn(activeCard === f.name), title: f.name,
              onClick: () => openCard(f.name),
            }, f.name.replace(/\.md$/, ''))),
          ),
          e('pre', { style: Object.assign({}, S.pre, { background: 'transparent', borderRadius: 0, maxHeight: small ? 360 : 520 }) }, cardBody || '选择一个主题卡进行预览'),
        ),
      );

      // ---------- 主题图页 ----------
      const graphTab = e('div', { style: S.content },
        e('div', { style: S.sectionHead },
          e('div', null,
            e('h3', { style: S.sectionTitle }, '主题关系'),
            e('div', { style: S.sectionDesc }, '节点大小代表事实数，连线代表主题中心相似度；点节点可聚焦'),
          ),
          e('span', { style: { flex: 1 } }),
          e('div', { style: S.pills },
            e('span', { style: S.pill }, `${(graph.nodes || []).length} 个主题`),
            e('span', { style: S.pill }, `${(graph.links || []).length} 条关联`),
            e('button', { style: S.pillBtn, title: '放大', onClick: () => setView((v) => ({ k: Math.min(3, v.k * 1.2), x: v.x, y: v.y })) }, '+'),
            e('button', { style: S.pillBtn, title: '缩小', onClick: () => setView((v) => ({ k: Math.max(0.45, v.k / 1.2), x: v.x, y: v.y })) }, '−'),
            e('button', { style: S.pillBtn, title: '重置视图（也会取消选中）', onClick: () => { setView({ k: 1, x: 0, y: 0 }); setPinnedNode(''); } }, '重置'),
          ),
        ),
        e('div', { ref: graphAreaRef, style: Object.assign({}, S.cardShell, S.graphWrap, { background: C.l1, touchAction: 'none' }) },
        (() => {
          const W = Math.max(420, Math.min(980, cw > 0 ? cw - 8 : 560));
          const H = Math.round(W * 0.52);
          const nodes = graph.nodes || [];
          const links = graph.links || [];
          if (!nodes.length) {
            return e('div', { style: S.empty },
              e('div', { style: S.emptyTitle }, '暂无主题关系'),
              e('div', { style: S.emptyDesc }, '当前没有可显示的主题或连线'),
            );
          }
          const pos = forceLayout(nodes, links, W, H);
          const idx = new Map(nodes.map((d, i) => [d.id, i]));
          // 每节点只保留相似度最高的 3 条线
          const best = new Map();
          links.forEach((l) => {
            [l.source, l.target].forEach((id) => {
              const arr = best.get(id) || [];
              arr.push(l);
              arr.sort((a, b) => (b.weight || 0) - (a.weight || 0));
              best.set(id, arr.slice(0, 3));
            });
          });
          const keep = new Set();
          best.forEach((arr) => arr.forEach((l) => keep.add(l.source + '|' + l.target)));
          const activeId = pinnedNode || hoverNode;
          const neighbours = new Set();
          if (activeId) {
            links.forEach((l) => {
              if (l.source === activeId) neighbours.add(l.target);
              if (l.target === activeId) neighbours.add(l.source);
            });
            neighbours.add(activeId);
          }
          return e('svg', { viewBox: `0 0 ${W} ${H}`, style: { display: 'block', width: '100%', height: 'auto', userSelect: 'none' }, preserveAspectRatio: 'xMidYMid meet' },
            e('g', { transform: `translate(${view.x} ${view.y}) scale(${view.k})` },
            e('defs', null,
              e('pattern', { id: 'mem0grid', width: 32, height: 32, patternUnits: 'userSpaceOnUse' },
                e('path', { d: 'M 32 0 L 0 0 0 32', fill: 'none', stroke: C.b1, strokeWidth: 1, strokeOpacity: 0.35 })),
              e('pattern', { id: 'mem0grid2', width: 128, height: 128, patternUnits: 'userSpaceOnUse' },
                e('path', { d: 'M 128 0 L 0 0 0 128', fill: 'none', stroke: C.b1, strokeWidth: 1, strokeOpacity: 0.7 })),
            ),
            e('rect', { width: W, height: H, fill: 'url(#mem0grid)' }),
            e('rect', { width: W, height: H, fill: 'url(#mem0grid2)' }),
            [120, 240, 360].filter((r) => r < Math.min(W, H) / 2).map((r) => e('circle', {
              key: 'ring' + r, cx: W / 2, cy: H / 2, r, fill: 'none', stroke: C.b1,
              strokeWidth: 1, strokeOpacity: 0.6, strokeDasharray: '4 4',
            })),
            e('line', { x1: W / 2 - 8, y1: H / 2, x2: W / 2 + 8, y2: H / 2, stroke: C.b2 }),
            e('line', { x1: W / 2, y1: H / 2 - 8, x2: W / 2, y2: H / 2 + 8, stroke: C.b2 }),
            links.filter((l) => keep.has(l.source + '|' + l.target)).map((l, i) => {
              const a = pos[idx.get(l.source)], b = pos[idx.get(l.target)];
              if (!a || !b) return null;
              const related = !activeId || l.source === activeId || l.target === activeId;
              const wt = l.weight || 0;
              return e('line', {
                key: 'e' + i, x1: a.x, y1: a.y, x2: b.x, y2: b.y,
                stroke: related && activeId ? C.t2 : C.b3,
                strokeWidth: 1 + wt * 2,
                strokeOpacity: (!activeId ? 0.18 + wt * 0.62 : related ? 0.9 : 0.08),
                style: { transition: `stroke ${T.fast}, stroke-opacity ${T.fast}` },
              });
            }),
            nodes.map((d, i) => {
              const p = pos[i];
              const dim = activeId && !neighbours.has(d.id);
              const r = p.r;
              return e('g', {
                key: d.id, opacity: dim ? 0.28 : 1,
                style: { cursor: 'pointer', transition: `opacity ${T.fast}` },
                onMouseEnter: () => setHoverNode(d.id),
                onMouseLeave: () => setHoverNode(''),
                onClick: () => setPinnedNode((v) => (v === d.id ? '' : d.id)),
              },
                e('circle', {
                  cx: p.x, cy: p.y, r,
                  fill: d.pinned ? C.brand : C.l3,
                  stroke: d.pinned ? C.brand : C.b3,
                  strokeWidth: d.pinned ? 2 : 1.5,
                }),
                r >= 14 && e('text', {
                  x: p.x, y: p.y + 4, textAnchor: 'middle', fontSize: 12, fontWeight: 500,
                  fill: C.t1, style: NUM,
                }, d.facts || 0),
                e('text', {
                  x: p.x, y: p.y + r + 14, textAnchor: 'middle', fontSize: 12,
                  fill: d.pinned ? C.t1 : C.t2, fontWeight: d.pinned ? 600 : 400,
                }, (d.name || '').slice(0, 12)),
              );
            }),
          ),
          );
        })(),
        e('div', { style: S.legend },
          e('span', null, '节点大小 = 事实数'),
          e('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6 } },
            e('span', { style: { width: 10, height: 10, borderRadius: '50%', background: C.brand } }), '手动主题'),
          e('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6 } },
            e('span', { style: { width: 32, height: 1, background: C.b3 } }),
            e('span', { style: { width: 32, height: 3, background: C.b3 } }), '相似度'),
          e('span', { style: { color: C.cap } }, '节点位置仅用于布局'),
        ),
        ),
      );

      // ---------- ⌘K 命令面板 ----------
      const paletteEl = palette && e('div', { style: S.overlay, onClick: (ev) => { if (ev.target === ev.currentTarget) setPalette(false); } },
        e('div', { style: S.palette },
          e('div', { style: S.paletteHead },
            e('span', { style: { color: C.cap } }, '⌕'),
            e('input', {
              autoFocus: true, style: S.paletteInput, placeholder: '搜索记忆…', value: pq,
              onChange: (ev) => { setPq(ev.target.value); setPIdx(0); },
              onKeyDown: (ev) => {
                if (ev.key === 'ArrowDown') { ev.preventDefault(); setPIdx((i) => Math.min(i + 1, paletteList.length - 1)); }
                else if (ev.key === 'ArrowUp') { ev.preventDefault(); setPIdx((i) => Math.max(i - 1, 0)); }
                else if (ev.key === 'Enter') {
                  const hit = paletteList[pIdx];
                  setPalette(false); setTab('mem');
                  if (hit) { setItems([hit]); }
                }
              },
            }),
            e('span', { style: S.kbd }, 'Esc'),
          ),
          e('div', { style: S.paletteList },
            paletteList.map((it, i) => e('div', {
              key: it.id, style: S.paletteRow(i === pIdx),
              onMouseEnter: () => setPIdx(i),
              onClick: () => { setPalette(false); setTab('mem'); setItems([it]); },
            }, e('span', { style: S.paletteTxt }, it.memory))),
            !paletteList.length && e('div', { style: { height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.t2, fontSize: 14 } }, '没有匹配的记忆'),
          ),
        ),
      );

      return e('div', { style: S.root, ref: rootRef },
        e('style', null, '@keyframes mem0spin{to{transform:rotate(360deg)}}'),
        stateArea,
        noticeEl,
        tabsEl,
        tab === 'mem' && memTab,
        tab === 'card' && cardTab,
        tab === 'graph' && graphTab,
        paletteEl,
      );
    }

    /** 侧边栏底部的入口按钮（抄 dsh-mnemon 的「记忆系统」入口）。 */
    function SidebarEntry() {
      const [open, setOpen] = useState(pageStore.open);
      useEffect(() => pageStore.subscribe(setOpen), []);
      return React.createElement('button', {
        type: 'button',
        title: '长期记忆',
        onClick: () => pageStore.toggle(),
        style: {
          display: 'flex', alignItems: 'center', gap: 8, width: '100%', height: 36, padding: '0 10px',
          borderRadius: 8, border: 0, background: open ? 'var(--dsw-alias-interactive-bg-hover)' : 'transparent',
          color: 'var(--dsw-alias-label-secondary)', fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
        },
      }, React.createElement('span', { style: { fontSize: 13 } }, '◍'), React.createElement('span', { style: { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, '记忆'));
    }

    /** 全屏记忆页（在 shell.overlay 层渲染，铺满内容区）。 */
    function MemoryPage() {
      const [open, setOpen] = useState(pageStore.open);
      useEffect(() => pageStore.subscribe(setOpen), []);
      useEffect(() => {
        if (!open) return undefined;
        const onKey = (ev) => { if (ev.key === 'Escape') pageStore.set(false); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
      }, [open]);
      if (!open) return null;
      return React.createElement('div', {
        style: {
          position: 'fixed', inset: 0, zIndex: 1200, display: 'flex', flexDirection: 'column',
          background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)',
        },
      },
        React.createElement('div', {
          style: {
            flex: 'none', display: 'flex', alignItems: 'center', gap: 12, height: 52, padding: '0 24px',
            borderBottom: '1px solid var(--dsw-alias-border-l1)',
          },
        },
          React.createElement('span', { style: { fontSize: 15, fontWeight: 600 } }, '记忆系统'),
          React.createElement('span', { style: { flex: 1 } }),
          React.createElement('button', {
            type: 'button',
            onClick: () => pageStore.set(false),
            style: {
              width: 28, height: 28, borderRadius: 6, border: 0, background: 'transparent',
              color: 'var(--dsw-alias-label-secondary)', cursor: 'pointer', fontSize: 16,
            },
            title: '关闭（Esc）',
          }, '×'),
        ),
        React.createElement('div', { style: { flex: 1, overflowY: 'auto', padding: '20px 24px 32px' } },
          React.createElement(Panel, { full: true }),
        ),
      );
    }

    function apply(ctx) {
      const slots = ctx.get('slots');
      if (slots === undefined) return;
      // 设置页里保留一个精简入口
      slots.inject('settings.section', () => slots.register(
        { name: 'settings.section', id: 'mem0', order: 26, label: '记忆' },
        () => React.createElement(Panel),
      ));
      // 侧边栏入口 + 全屏页面
      slots.inject('sidebar.footer.action', () => slots.register(
        { name: 'sidebar.footer.action', id: 'mem0-entry' },
        () => React.createElement(SidebarEntry),
      ));
      slots.inject('shell.overlay', () => slots.register(
        { name: 'shell.overlay', id: 'mem0-page' },
        () => React.createElement(MemoryPage),
      ));
    }

    return { name: 'dsh-mem0', apply };
  },
});
