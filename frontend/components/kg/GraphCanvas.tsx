"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { bounds, layout, type Point } from "@/lib/graphLayout";
import { RELATION_TEXT, SYSTEM_COLOR, edgeColor, nodeSystem, shortLabel } from "@/lib/kg";
import type { GraphNode, KgEdge, LinkEdge } from "@/lib/types";

export type EvidenceLink = { id: string; paper: string; concept: string };
type View = { tx: number; ty: number; k: number };
type Hover = { kind: "node" | "edge"; id: string; x: number; y: number } | null;

const PAPER_COLOR = "#8ea3ad";

function radius(n: GraphNode, degree: number) {
  if (n.type === "paper") return 6;
  return Math.min(20, 9 + Math.sqrt(degree) * 2.6);
}

export default function GraphCanvas({
  nodes,
  edges,
  links,
  evidence,
  focusId,
  selectedEdge,
  selectedNode,
  onSelectEdge,
  onSelectNode,
  showPaperLabels,
}: {
  nodes: GraphNode[];
  edges: KgEdge[];
  links: LinkEdge[];
  evidence: EvidenceLink[];
  focusId: string | null;
  selectedEdge: string | null;
  selectedNode: string | null;
  onSelectEdge: (id: string) => void;
  onSelectNode: (id: string) => void;
  showPaperLabels: boolean;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 900, h: 600 });
  const [hover, setHover] = useState<Hover>(null);
  const [dragging, setDragging] = useState(false);

  // ---- layout (pure function of the visible graph)
  const degree = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of edges) {
      d.set(e.src, (d.get(e.src) ?? 0) + 1);
      d.set(e.dst, (d.get(e.dst) ?? 0) + 1);
    }
    return d;
  }, [edges]);
  // Only the best-connected concepts are labelled by default, so the first view is readable.
  // Everything else gets a label on hover, when selected / focused, or once you zoom in.
  const keyLabels = useMemo(() => {
    const concepts = nodes.filter((n) => n.type === "concept");
    const top = [...concepts].sort((a, b) => (degree.get(b.node_id) ?? 0) - (degree.get(a.node_id) ?? 0)).slice(0, 12);
    return new Set(top.map((n) => n.node_id));
  }, [nodes, degree]);
  const layoutKey = useMemo(
    () => [nodes.map((n) => n.node_id).join(","), edges.length, links.length, evidence.length, focusId].join("|"),
    [nodes, edges, links, evidence, focusId],
  );
  const basePos = useMemo(() => {
    const ln = nodes.map((n) => ({ id: n.node_id, r: radius(n, degree.get(n.node_id) ?? 0), pinned: n.node_id === focusId }));
    const ll = [
      ...edges.map((e) => ({ source: e.src, target: e.dst, strength: 1, length: 200 })),
      ...links.map((l) => ({ source: l.src, target: l.dst, strength: l.relation === "IS_A" ? 0.9 : 0.25, length: l.relation === "IS_A" ? 160 : 90 })),
      ...evidence.map((v) => ({ source: v.paper, target: v.concept, strength: 0.3, length: 120 })),
    ];
    return layout(ln, ll);
    // layoutKey captures every input that changes the picture
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey]);

  // node drags and the view are kept per layout, so a new graph starts fitted and undragged
  const [moved, setMoved] = useState<{ key: string; pos: Record<string, Point> }>({ key: "", pos: {} });
  const pos = (id: string): Point | undefined => (moved.key === layoutKey ? moved.pos[id] : undefined) ?? basePos.get(id);

  const fitView = useMemo((): View => {
    const b = bounds([...basePos.values()], 70);
    const k = Math.max(0.25, Math.min(size.w / b.w, size.h / b.h, 1.5));
    return { k, tx: size.w / 2 - k * (b.x + b.w / 2), ty: size.h / 2 - k * (b.y + b.h / 2) };
  }, [basePos, size]);
  const [viewState, setViewState] = useState<{ key: string; v: View } | null>(null);
  const view = viewState && viewState.key === layoutKey ? viewState.v : fitView;
  const setView = (v: View) => setViewState({ key: layoutKey, v });
  const zoomBy = (f: number) => {
    const k = Math.max(0.2, Math.min(4, view.k * f));
    const cx = size.w / 2;
    const cy = size.h / 2;
    setView({ k, tx: cx - ((cx - view.tx) / view.k) * k, ty: cy - ((cy - view.ty) / view.k) * k });
  };

  // ---- size + wheel zoom (native listeners: React's wheel handler is passive)
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setSize({ w: entry.contentRect.width || 900, h: entry.contentRect.height || 600 }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const viewRef = useRef(view);
  const keyRef = useRef(layoutKey);
  useEffect(() => {
    viewRef.current = view;
    keyRef.current = layoutKey;
  });
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const r = svg.getBoundingClientRect();
      const mx = ev.clientX - r.left;
      const my = ev.clientY - r.top;
      const v = viewRef.current;
      const k = Math.max(0.2, Math.min(4, v.k * Math.exp(-ev.deltaY * 0.0015)));
      setViewState({ key: keyRef.current, v: { k, tx: mx - ((mx - v.tx) / v.k) * k, ty: my - ((my - v.ty) / v.k) * k } });
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  // ---- pan + node drag
  const drag = useRef<{ mode: "pan" | "node"; id?: string; sx: number; sy: number; v: View; p?: Point; movedPx: number } | null>(null);
  function onDown(ev: React.MouseEvent, nodeId?: string) {
    ev.stopPropagation();
    const p = nodeId ? pos(nodeId) : undefined;
    drag.current = { mode: nodeId ? "node" : "pan", id: nodeId, sx: ev.clientX, sy: ev.clientY, v: view, p, movedPx: 0 };
    setDragging(true);
    const move = (e: MouseEvent) => {
      const d = drag.current;
      if (!d) return;
      const dx = e.clientX - d.sx;
      const dy = e.clientY - d.sy;
      d.movedPx = Math.max(d.movedPx, Math.abs(dx) + Math.abs(dy));
      if (d.mode === "pan") setView({ ...d.v, tx: d.v.tx + dx, ty: d.v.ty + dy });
      else if (d.id && d.p) {
        const np = { x: d.p.x + dx / d.v.k, y: d.p.y + dy / d.v.k };
        setMoved((m) => ({ key: layoutKey, pos: { ...(m.key === layoutKey ? m.pos : {}), [d.id!]: np } }));
      }
    };
    const up = () => {
      const d = drag.current;
      drag.current = null;
      setDragging(false);
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      if (d && d.mode === "node" && d.id && d.movedPx < 4) onSelectNode(d.id);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  // ---- highlight set
  const focusSet = useMemo(() => {
    if (selectedEdge) {
      const e = edges.find((x) => x.edge_id === selectedEdge);
      return e ? new Set([e.src, e.dst, e.paper.paper_id]) : null;
    }
    if (selectedNode) {
      const s = new Set([selectedNode]);
      const addIf = (a: string, b: string) => {
        if (a === selectedNode || b === selectedNode) {
          s.add(a);
          s.add(b);
        }
      };
      for (const e of edges) addIf(e.src, e.dst);
      for (const l of links) addIf(l.src, l.dst);
      for (const v of evidence) addIf(v.paper, v.concept);
      return s;
    }
    return null;
  }, [selectedEdge, selectedNode, edges, links, evidence]);
  const dim = (id: string) => (focusSet && !focusSet.has(id) ? 0.22 : 1);

  // ---- parallel relation edges get separate curves
  const curveOffset = useMemo(() => {
    const groups = new Map<string, string[]>();
    for (const e of edges) {
      const k = [e.src, e.dst].sort().join("~");
      groups.set(k, [...(groups.get(k) ?? []), e.edge_id]);
    }
    const off = new Map<string, number>();
    groups.forEach((ids) => ids.forEach((id, i) => off.set(id, (i - (ids.length - 1) / 2) * 26)));
    return off;
  }, [edges]);

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.node_id, n])), [nodes]);
  const rOf = (id: string) => {
    const n = nodeById.get(id);
    return n ? radius(n, degree.get(id) ?? 0) : 8;
  };

  function curve(src: string, dst: string, offset: number) {
    const a = pos(src);
    const b = pos(dst);
    if (!a || !b) return null;
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const cx = mx + (-dy / len) * offset;
    const cy = my + (dx / len) * offset;
    const trim = (p: Point, c: { x: number; y: number }, r: number) => {
      const vx = c.x - p.x;
      const vy = c.y - p.y;
      const l = Math.sqrt(vx * vx + vy * vy) || 1;
      return { x: p.x + (vx / l) * r, y: p.y + (vy / l) * r };
    };
    const s = trim(a, { x: cx, y: cy }, rOf(src) + 1);
    const t = trim(b, { x: cx, y: cy }, rOf(dst) + 4);
    return { d: `M${s.x},${s.y} Q${cx},${cy} ${t.x},${t.y}`, mid: { x: (s.x + 2 * cx + t.x) / 4, y: (s.y + 2 * cy + t.y) / 4 } };
  }

  const hoverNode = hover?.kind === "node" ? nodeById.get(hover.id) : undefined;
  const hoverEdge = hover?.kind === "edge" ? edges.find((e) => e.edge_id === hover.id) : undefined;
  const markerColors = ["#047857", "#d97706", "#8a9ba4", "#d14343", "#0e7490", "#b9c6cc"];

  return (
    <div ref={wrapRef} className="kg-canvas">
      <svg ref={svgRef} className={dragging ? "dragging" : undefined} viewBox={`0 0 ${size.w} ${size.h}`} onMouseDown={(e) => onDown(e)}>
        <defs>
          {markerColors.map((c) => (
            <marker key={c} id={`arr-${c.slice(1)}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={c} />
            </marker>
          ))}
        </defs>
        <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}>
          {/* paper → concept evidence links (derived from each edge's source paper) */}
          {evidence.map((v) => {
            const a = pos(v.paper);
            const b = pos(v.concept);
            if (!a || !b) return null;
            return (
              <line key={v.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#d5dee3" strokeWidth={1} opacity={Math.min(dim(v.paper), dim(v.concept))} />
            );
          })}
          {/* citations + ontology links */}
          {links.map((l) => {
            const c = curve(l.src, l.dst, 0);
            if (!c) return null;
            const isa = l.relation === "IS_A";
            const color = isa ? "#0e7490" : "#b9c6cc";
            return (
              <path
                key={l.edge_id}
                d={c.d}
                fill="none"
                stroke={color}
                strokeWidth={isa ? 1.4 : 1}
                strokeDasharray={isa ? "5 4" : "2 3"}
                markerEnd={`url(#arr-${color.slice(1)})`}
                opacity={Math.min(dim(l.src), dim(l.dst))}
              />
            );
          })}
          {/* agent-established relations */}
          {edges.map((e) => {
            const c = curve(e.src, e.dst, curveOffset.get(e.edge_id) ?? 0);
            if (!c) return null;
            const color = edgeColor(e);
            const sel = e.edge_id === selectedEdge;
            const op = focusSet ? (sel || (!selectedEdge && focusSet.has(e.src) && focusSet.has(e.dst)) ? 1 : 0.15) : 1;
            return (
              <g key={e.edge_id} opacity={op}>
                {sel && <path d={c.d} fill="none" stroke={color} strokeWidth={7} opacity={0.22} />}
                <path
                  d={c.d}
                  fill="none"
                  stroke={color}
                  strokeWidth={sel ? 2.6 : 1.7}
                  strokeDasharray={e.status === "REJECTED" ? "6 4" : e.relation === "NO_ASSOCIATION_WITH" ? "2 3" : undefined}
                  markerEnd={`url(#arr-${color.slice(1)})`}
                />
                <path
                  d={c.d}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={12}
                  style={{ cursor: "pointer" }}
                  onMouseDown={(ev) => ev.stopPropagation()}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    onSelectEdge(e.edge_id);
                  }}
                  onMouseMove={(ev) => {
                    const r = wrapRef.current!.getBoundingClientRect();
                    setHover({ kind: "edge", id: e.edge_id, x: ev.clientX - r.left, y: ev.clientY - r.top });
                  }}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            );
          })}
          {/* nodes */}
          {nodes.map((n) => {
            const p = pos(n.node_id);
            if (!p) return null;
            const r = radius(n, degree.get(n.node_id) ?? 0);
            const sys = nodeSystem(n);
            const sel = n.node_id === selectedNode;
            const isFocus = n.node_id === focusId;
            const color = sys === "PAPER" ? PAPER_COLOR : SYSTEM_COLOR[sys] ?? SYSTEM_COLOR.FREE;
            return (
              <g
                key={n.node_id}
                transform={`translate(${p.x},${p.y})`}
                opacity={dim(n.node_id)}
                style={{ cursor: "pointer" }}
                onMouseDown={(ev) => onDown(ev, n.node_id)}
                onMouseMove={(ev) => {
                  const rr = wrapRef.current!.getBoundingClientRect();
                  setHover({ kind: "node", id: n.node_id, x: ev.clientX - rr.left, y: ev.clientY - rr.top });
                }}
                onMouseLeave={() => setHover(null)}
              >
                {(sel || isFocus) && (
                  <circle r={r + 5} fill="none" stroke={sel ? "#10b981" : "#0e5f73"} strokeWidth={2} strokeDasharray={isFocus && !sel ? "3 2" : undefined} />
                )}
                {sys === "PAPER" ? (
                  <rect x={-r} y={-r} width={r * 2} height={r * 2} rx={1.5} fill="#fff" stroke={color} strokeWidth={1.6} />
                ) : (
                  <circle r={r} fill={sys === "FREE" ? "#fff" : color} stroke={sys === "FREE" ? color : "#fff"} strokeWidth={sys === "FREE" ? 1.6 : 2} strokeDasharray={sys === "FREE" ? "3 2" : undefined} />
                )}
                {n.type === "concept" &&
                  (sel || isFocus || hover?.id === n.node_id || view.k >= 1.6 || (focusSet ? focusSet.has(n.node_id) : keyLabels.has(n.node_id))) && (
                  <text className="kg-node-label" y={r + 4 + 11 / Math.min(1, view.k)} textAnchor="middle" fontWeight={isFocus ? 650 : 500} style={{ fontSize: 11 / Math.min(1, view.k) }}>
                    {shortLabel(n.label)}
                  </text>
                )}
                {n.type === "paper" && showPaperLabels && (
                  <text className="kg-node-label" y={r + 3 + 10 / Math.min(1, view.k)} textAnchor="middle" style={{ fontSize: 9.5 / Math.min(1, view.k), fill: "#5d717b" }}>
                    {n.year ?? ""}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {hover && (hoverNode || hoverEdge) && (
        <div className="kg-tooltip" style={{ left: Math.min(hover.x + 14, size.w - 330), top: hover.y + 14 }}>
          {hoverNode?.type === "concept" && (
            <>
              <div className="t">{hoverNode.label}</div>
              <div>
                {hoverNode.node_id}
                {hoverNode.pool_patients ? ` · ${hoverNode.pool_patients} pool patients` : ""}
              </div>
            </>
          )}
          {hoverNode?.type === "paper" && (
            <>
              <div className="t">{hoverNode.label}</div>
              <div>
                {hoverNode.node_id}
                {hoverNode.year ? ` · ${hoverNode.year}` : ""}
              </div>
            </>
          )}
          {hoverEdge && (
            <>
              <div className="t">
                {shortLabel(nodeById.get(hoverEdge.src)?.label ?? hoverEdge.src, 40)} {RELATION_TEXT[hoverEdge.relation] ?? hoverEdge.relation}{" "}
                {shortLabel(nodeById.get(hoverEdge.dst)?.label ?? hoverEdge.dst, 40)}
              </div>
              <div>
                {hoverEdge.status} · literature {hoverEdge.sanity.literature ?? "—"} · pool {hoverEdge.sanity.pool ?? "—"}
              </div>
              <div style={{ opacity: 0.8 }}>Click to inspect the evidence</div>
            </>
          )}
        </div>
      )}
      <div className="kg-zoom">
        <button className="secondary sm" onClick={() => zoomBy(1.25)} title="Zoom in">＋</button>
        <button className="secondary sm" onClick={() => zoomBy(0.8)} title="Zoom out">－</button>
        <button className="secondary sm" onClick={() => setViewState(null)} title="Fit graph to screen">Fit</button>
        <button className="secondary sm" onClick={() => setMoved({ key: "", pos: {} })} title="Undo node drags">Reset layout</button>
      </div>
    </div>
  );
}
