// Small deterministic force-directed layout (no dependency). Good for the ~10–150 nodes the graph API returns.
// Same input → same picture, so a demo looks the same every time.

export type LayoutNode = { id: string; r: number; pinned?: boolean };
export type LayoutLink = { source: string; target: string; strength: number; length: number };
export type Point = { x: number; y: number };

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

export function layout(nodes: LayoutNode[], links: LayoutLink[], iterations = 420): Map<string, Point> {
  const n = nodes.length;
  const pos = new Map<string, Point & { vx: number; vy: number }>();
  const radius = 60 + Math.sqrt(n) * 38;
  nodes.forEach((nd, i) => {
    if (nd.pinned) {
      pos.set(nd.id, { x: 0, y: 0, vx: 0, vy: 0 });
      return;
    }
    const a = (i / Math.max(1, n)) * Math.PI * 2 + hash(nd.id) * 0.8;
    const rr = radius * (0.55 + hash(nd.id + "r") * 0.6);
    pos.set(nd.id, { x: Math.cos(a) * rr, y: Math.sin(a) * rr, vx: 0, vy: 0 });
  });
  const ids = nodes.map((d) => d.id);
  const rOf = new Map(nodes.map((d) => [d.id, d.r]));
  const pinned = new Set(nodes.filter((d) => d.pinned).map((d) => d.id));
  const repulse = 9000;

  for (let it = 0; it < iterations; it++) {
    const alpha = 1 - it / iterations;
    const cool = 0.08 + alpha * 0.9;
    // repulsion
    for (let i = 0; i < n; i++) {
      const a = pos.get(ids[i])!;
      for (let j = i + 1; j < n; j++) {
        const b = pos.get(ids[j])!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) {
          dx = hash(ids[i] + ids[j]) - 0.5;
          dy = hash(ids[j] + ids[i]) - 0.5;
          d2 = 0.01;
        }
        const d = Math.sqrt(d2);
        const minD = (rOf.get(ids[i]) ?? 8) + (rOf.get(ids[j]) ?? 8) + 34;
        const f = repulse / d2 + (d < minD ? (minD - d) * 0.6 : 0);
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }
    // springs
    for (const l of links) {
      const a = pos.get(l.source);
      const b = pos.get(l.target);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d - l.length) * 0.06 * l.strength;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }
    // gravity + integrate
    for (const id of ids) {
      const p = pos.get(id)!;
      if (pinned.has(id)) {
        p.vx = p.vy = 0;
        continue;
      }
      p.vx -= p.x * 0.007;
      p.vy -= p.y * 0.007;
      const sp = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
      const cap = 40 * cool;
      if (sp > cap) {
        p.vx = (p.vx / sp) * cap;
        p.vy = (p.vy / sp) * cap;
      }
      p.x += p.vx * cool;
      p.y += p.vy * cool;
      p.vx *= 0.55;
      p.vy *= 0.55;
    }
  }
  const out = new Map<string, Point>();
  pos.forEach((p, id) => out.set(id, { x: p.x, y: p.y }));
  return out;
}

export function bounds(points: Point[], pad = 60) {
  if (!points.length) return { x: -200, y: -150, w: 400, h: 300 };
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of points) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }
  return { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
}
