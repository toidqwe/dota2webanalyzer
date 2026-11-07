/* OTA charts — dependency-free SVG rendering */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  let uid = 0;

  const COLORS = {
    radiant: "#4fbf73",
    dire: "#e2564f",
    gold: "#d9a441",
    grid: "rgba(255,255,255,.07)",
    text: "#7d8798",
    dim: "#566072",
  };

  function el(name, attrs) {
    const node = document.createElementNS(NS, name);
    if (attrs) for (const key in attrs) node.setAttribute(key, attrs[key]);
    return node;
  }

  function fmtInt(value) {
    return Math.round(value).toLocaleString("ru-RU").replace(/\u00a0/g, " ");
  }

  function escHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }

  function fmtShort(value) {
    const abs = Math.abs(value);
    if (abs >= 1000) {
      const k = value / 1000;
      return (k >= 10 ? Math.round(k) : k.toFixed(1).replace(".0", "")) + "k";
    }
    return String(Math.round(value));
  }

  function niceStep(max) {
    const raw = max / 2;
    const pow = Math.pow(10, Math.floor(Math.log10(Math.max(1, raw))));
    const norm = raw / pow;
    let step;
    if (norm <= 1) step = 1;
    else if (norm <= 2) step = 2;
    else if (norm <= 5) step = 5;
    else step = 10;
    return step * pow;
  }

  function minuteLabel(minute) {
    if (minute >= 60) return Math.floor(minute / 60) + "ч";
    return minute + "м";
  }

  function eventsAt(analysis, minute) {
    const t0 = minute * 60;
    const t1 = t0 + 60;
    const out = [];
    (analysis.objectives || []).filter((o) => o.time >= t0 && o.time < t1).slice(0, 2).forEach((o) => {
      out.push(`${o.time_label} · ${o.team === "radiant" ? "Radiant" : o.team === "dire" ? "Dire" : "?"} — ${o.label}`);
    });
    (analysis.fights || []).filter((f) => f.start >= t0 && f.start < t1).slice(0, 1).forEach((f) => {
      out.push(`${f.time} · драка ${f.radiant_deaths}:${f.dire_deaths} (${f.winner === "radiant" ? "Radiant" : f.winner === "dire" ? "Dire" : "ничья"})`);
    });
    (analysis.turning_points || []).filter((p) => Math.abs(p.minute - minute) <= 1).slice(0, 1).forEach((p) => {
      out.push(`Перелом: ${p.title}`);
    });
    return out.slice(0, 3);
  }

  function advantage(container, analysis, metric) {
    const svg = container.querySelector("svg");
    const tip = container.querySelector(".chart-tip");
    if (!svg) return;
    const width = Math.max(320, container.clientWidth);
    const height = Math.max(220, container.clientHeight);
    const margin = { l: 56, r: 16, t: 18, b: 26 };
    const innerW = width - margin.l - margin.r;
    const innerH = height - margin.t - margin.b;
    const minutes = analysis.timeline.minutes || [];
    const last = Math.max(1, minutes.length - 1);
    const isProb = metric === "prob";
    const values = metric === "gold" ? analysis.timeline.gold : metric === "xp" ? analysis.timeline.xp : analysis.timeline.prob;
    svg.innerHTML = "";
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);

    const maxAbsRaw = isProb ? 100 : Math.max(1000, ...values.map((v) => Math.abs(v)));
    const step = isProb ? 25 : niceStep(maxAbsRaw);
    const maxAbs = isProb ? 100 : Math.ceil(maxAbsRaw / step) * step;
    const baseline = isProb ? 50 : 0;
    const y = (v) => margin.t + (isProb ? (100 - v) / 100 : (maxAbs - v) / (2 * maxAbs)) * innerH;
    const x = (m) => margin.l + (m / last) * innerW;
    const zeroY = y(baseline);

    const defs = el("defs");
    const id = "grad" + ++uid;
    const gradUp = el("linearGradient", { id: id + "u", x1: "0", y1: "0", x2: "0", y2: "1" });
    gradUp.append(el("stop", { offset: "0%", "stop-color": COLORS.radiant, "stop-opacity": ".42" }));
    gradUp.append(el("stop", { offset: "100%", "stop-color": COLORS.radiant, "stop-opacity": "0" }));
    const gradDown = el("linearGradient", { id: id + "d", x1: "0", y1: "1", x2: "0", y2: "0" });
    gradDown.append(el("stop", { offset: "0%", "stop-color": COLORS.dire, "stop-opacity": ".42" }));
    gradDown.append(el("stop", { offset: "100%", "stop-color": COLORS.dire, "stop-opacity": "0" }));
    defs.append(gradUp, gradDown);
    const clipUp = el("clipPath", { id: id + "cu" });
    clipUp.append(el("rect", { x: 0, y: 0, width: width, height: Math.max(0, zeroY) }));
    const clipDown = el("clipPath", { id: id + "cd" });
    clipDown.append(el("rect", { x: 0, y: zeroY, width: width, height: Math.max(0, height - zeroY) }));
    defs.append(clipUp, clipDown);
    svg.append(defs);

    // phase bands
    const bands = [
      { from: 0, to: 10, label: "Лейнинг" },
      { from: 10, to: 25, label: "Мид" },
      { from: 25, to: last, label: "Лейт" },
    ];
    bands.forEach((b, i) => {
      if (b.from >= last) return;
      const bx = x(Math.min(b.to, last));
      const bw = bx - x(b.from);
      if (i > 0) {
        svg.append(el("rect", { x: x(b.from), y: margin.t, width: bw, height: innerH, fill: "rgba(255,255,255,.012)" }));
      }
      if (bw > 70) {
        const t = el("text", { x: x(b.from) + bw / 2, y: margin.t + 12, fill: "#4d5667", "font-size": 9, "text-anchor": "middle", "letter-spacing": "1.4", "font-family": "Segoe UI, sans-serif" });
        t.textContent = b.label.toUpperCase();
        svg.append(t);
      }
    });

    // grid
    for (let v = baseline - maxAbs; v <= baseline + maxAbs + 0.001; v += step) {
      if (isProb && (v < 0 || v > 100)) continue;
      const gy = y(v);
      svg.append(el("line", { x1: margin.l, x2: width - margin.r, y1: gy, y2: gy, stroke: v === baseline ? "rgba(255,255,255,.16)" : COLORS.grid, "stroke-width": 1, "stroke-dasharray": v === baseline ? "4 4" : "0" }));
      const label = el("text", { x: margin.l - 10, y: gy + 3.5, fill: COLORS.text, "font-size": 9.5, "text-anchor": "end", "font-family": "Segoe UI, sans-serif" });
      label.textContent = isProb ? Math.round(v) + "%" : (v > 0 ? "+" : v < 0 ? "−" : "") + fmtShort(Math.abs(v));
      svg.append(label);
    }

    // x labels
    const xStep = last > 30 ? 10 : 5;
    for (let m = 0; m <= last; m += xStep) {
      const gx = x(m);
      svg.append(el("line", { x1: gx, x2: gx, y1: margin.t, y2: height - margin.b, stroke: "rgba(255,255,255,.035)", "stroke-width": 1 }));
      const label = el("text", { x: gx, y: height - 8, fill: COLORS.text, "font-size": 9.5, "text-anchor": "middle", "font-family": "Segoe UI, sans-serif" });
      label.textContent = minuteLabel(m);
      svg.append(label);
    }

    // area + lines
    const pts = values.map((v, i) => [x(i), y(v)]);
    const areaD = `M ${x(0)} ${zeroY} ` + pts.map((p) => `L ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ") + ` L ${x(last)} ${zeroY} Z`;
    const lineD = pts.map((p, i) => `${i ? "L" : "M"} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
    svg.append(el("path", { d: areaD, fill: `url(#${id}u)`, "clip-path": `url(#${id}cu)` }));
    svg.append(el("path", { d: areaD, fill: `url(#${id}d)`, "clip-path": `url(#${id}cd)` }));
    svg.append(el("path", { d: lineD, fill: "none", stroke: COLORS.radiant, "stroke-width": 1.9, "clip-path": `url(#${id}cu)` }));
    svg.append(el("path", { d: lineD, fill: "none", stroke: COLORS.dire, "stroke-width": 1.9, "clip-path": `url(#${id}cd)` }));

    // markers
    (analysis.turning_points || []).slice(0, 5).forEach((p, i) => {
      if (p.minute > last) return;
      const mx = x(p.minute);
      const my = y(values[Math.min(last, Math.max(0, p.minute))] ?? baseline);
      svg.append(el("line", { x1: mx, x2: mx, y1: margin.t, y2: height - margin.b, stroke: "rgba(217,164,65,.22)", "stroke-width": 1, "stroke-dasharray": "3 4" }));
      svg.append(el("circle", { cx: mx, cy: my, r: 3, fill: COLORS.gold, stroke: "#0a0c11", "stroke-width": 1.5 }));
      const tag = el("g", { transform: `translate(${mx}, ${margin.t - 3})` });
      tag.append(el("circle", { r: 7, fill: "rgba(217,164,65,.14)", stroke: "rgba(217,164,65,.5)", "stroke-width": 1 }));
      const txt = el("text", { y: 3, fill: "#f1cb7c", "font-size": 8.5, "text-anchor": "middle", "font-weight": "700", "font-family": "Segoe UI, sans-serif" });
      txt.textContent = String(i + 1);
      tag.append(txt);
      svg.append(tag);
    });

    // crosshair
    const cross = el("line", { x1: 0, x2: 0, y1: margin.t, y2: height - margin.b, stroke: "rgba(255,255,255,.35)", "stroke-width": 1, visibility: "hidden" });
    const crossDot = el("circle", { r: 4, fill: "#fff", stroke: "#0a0c11", "stroke-width": 2, visibility: "hidden" });
    svg.append(cross, crossDot);
    const overlay = el("rect", { x: margin.l, y: margin.t, width: innerW, height: innerH, fill: "transparent" });
    svg.append(overlay);

    function hide() {
      cross.setAttribute("visibility", "hidden");
      crossDot.setAttribute("visibility", "hidden");
      if (tip) tip.hidden = true;
    }

    overlay.addEventListener("pointermove", (event) => {
      const rect = svg.getBoundingClientRect();
      const px = ((event.clientX - rect.left) / rect.width) * width;
      const minute = Math.max(0, Math.min(last, Math.round(((px - margin.l) / innerW) * last)));
      const value = values[minute] ?? 0;
      const cx = x(minute);
      const cy = y(value);
      cross.setAttribute("x1", cx);
      cross.setAttribute("x2", cx);
      cross.setAttribute("visibility", "visible");
      crossDot.setAttribute("cx", cx);
      crossDot.setAttribute("cy", cy);
      crossDot.setAttribute("visibility", "visible");
      if (!tip) return;
      tip.hidden = false;
      const evs = eventsAt(analysis, minute);
      const prob = analysis.timeline.prob[minute] ?? 50;
      const valueText = isProb ? (value).toFixed(0) + "%" : (value > 0 ? "+" : "") + fmtInt(value);
      const leadTeam = (isProb ? value : value) >= (isProb ? 50 : 0) ? "Radiant" : "Dire";
      tip.innerHTML = `<b>${minute}:00</b>
        <div class="tip-row"><span>${isProb ? "Шансы Radiant" : metric === "xp" ? "Опыт" : "Золото"}</span><span style="color:${leadTeam === "Radiant" ? COLORS.radiant : COLORS.dire};font-weight:700">${escHtml(valueText)}</span></div>
        <div class="tip-row"><span>Шансы Radiant</span><span>${prob.toFixed(0)}%</span></div>
        ${evs.length ? `<div class="tip-events">${evs.map((e) => `<div>${escHtml(e)}</div>`).join("")}</div>` : ""}`;
      const offsetX = (cx / width) * container.clientWidth;
      const offsetY = (cy / height) * container.clientHeight;
      const clampedX = Math.max(95, Math.min(container.clientWidth - 95, offsetX));
      tip.style.left = clampedX + "px";
      tip.style.top = Math.max(62, offsetY) + "px";
    });
    overlay.addEventListener("pointerleave", hide);
    svg.addEventListener("pointerleave", hide);
  }

  function radar(svg, grades, color) {
    if (!svg) return;
    const keys = [
      ["economy", "Эко"],
      ["combat", "Бой"],
      ["survival", "Жив"],
      ["vision", "Вижн"],
      ["objectives", "Объ"],
      ["discipline", "Дисц"],
    ];
    const width = 220;
    const height = 196;
    const cx = width / 2;
    const cy = 94;
    const radius = 68;
    svg.innerHTML = "";
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const pt = (i, r) => {
      const angle = (Math.PI * 2 * i) / keys.length - Math.PI / 2;
      return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r];
    };
    for (let ring = 1; ring <= 3; ring++) {
      const points = keys.map((_, i) => pt(i, (radius * ring) / 3).join(",")).join(" ");
      svg.append(el("polygon", { points, fill: ring === 3 ? "rgba(255,255,255,.015)" : "none", stroke: "rgba(255,255,255,.07)", "stroke-width": 1 }));
    }
    keys.forEach((_, i) => {
      const [ex, ey] = pt(i, radius);
      svg.append(el("line", { x1: cx, y1: cy, x2: ex, y2: ey, stroke: "rgba(255,255,255,.06)", "stroke-width": 1 }));
    });
    const valuePoints = keys.map(([key], i) => {
      const value = Math.max(6, Math.min(100, grades[key] ?? 50));
      return pt(i, (value / 100) * radius).join(",");
    });
    svg.append(el("polygon", { points: valuePoints.join(" "), fill: color + "26", stroke: color, "stroke-width": 1.6, "stroke-linejoin": "round" }));
    keys.forEach(([, label], i) => {
      const [ex, ey] = pt(i, radius + 17);
      const anchor = Math.abs(ex - cx) < 6 ? "middle" : ex < cx ? "end" : "start";
      const t = el("text", { x: ex, y: ey + 3, fill: "#8791a3", "font-size": 9, "text-anchor": anchor, "font-family": "Segoe UI, sans-serif" });
      t.textContent = label;
      svg.append(t);
    });
  }

  function ring(value, color) {
    const size = 76;
    const r = 32;
    const c = 2 * Math.PI * r;
    const pct = Math.max(0, Math.min(100, value)) / 100;
    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="6"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round"
        stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - pct)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
      <text x="${size / 2}" y="${size / 2 + 1}" text-anchor="middle" class="ring-val">${Math.round(value)}</text>
      <text x="${size / 2}" y="${size / 2 + 15}" text-anchor="middle" class="ring-cap">ИНДЕКС</text>
    </svg>`;
  }

  window.OTACharts = { advantage, radar, ring, fmtInt };
})();
