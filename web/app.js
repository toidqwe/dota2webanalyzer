/* OTA — front-end application */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const state = {
    data: null,
    metric: "gold",
    team: "all",
    mistakeTeam: "all",
    radarTimer: 0,
    chartTimer: 0,
    pollTimer: 0,
    elapsedTimer: 0,
    replayId: null,
    progressStartedAt: 0,
  };

  const esc = (value) =>
    String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

  const fmt = (value) => Number(Math.round(value || 0)).toLocaleString("ru-RU").replace(/\u00a0/g, " ");
  const signed = (value) => (value > 0 ? "+" : value < 0 ? "−" : "") + fmt(Math.abs(value));
  const pct = (value) => Math.round(value) + "%";
  const plural = (n, one, few, many) => {
    const abs = Math.abs(Math.round(n));
    if (abs % 10 === 1 && abs % 100 !== 11) return one;
    if (abs % 10 >= 2 && abs % 10 <= 4 && !(abs % 100 >= 12 && abs % 100 <= 14)) return few;
    return many;
  };

  const TEAM = { radiant: "Radiant", dire: "Dire" };

  function initials(name) {
    return String(name || "?").replace(/[^A-Za-zА-Яа-я0-9]/g, "").slice(0, 2).toUpperCase() || "?";
  }

  function portrait(hero, cls) {
    const color = hero.attr_color || "#d9a441";
    return `<div class="portrait ${cls || ""}" style="--hero-color:${esc(color)}" title="${esc(hero.name)}">
      <span>${esc(initials(hero.name))}</span>
      <img src="${esc(hero.img)}" alt="${esc(hero.name)}" loading="lazy" onerror="this.remove()">
    </div>`;
  }

  function gradeColor(value) {
    if (value >= 70) return "#4fbf73";
    if (value >= 50) return "#d9a441";
    return "#e2564f";
  }

  function gradeRows(grades) {
    const labels = { economy: "Экономика", combat: "Бой", survival: "Выживаемость", vision: "Вижн", objectives: "Объекты", discipline: "Дисциплина" };
    return Object.keys(labels)
      .map(
        (key) => `<div class="grade-row"><span>${labels[key]}</span>
          <div class="grade-track"><i style="width:${Math.max(2, grades[key])}%;background:${gradeColor(grades[key])}"></i></div>
          <span class="gv">${Math.round(grades[key])}</span></div>`
      )
      .join("");
  }

  function miniGrades(grades) {
    const labels = { economy: "Эко", combat: "Бой", survival: "Жив", vision: "Вижн", objectives: "Объ", discipline: "Дисц" };
    return Object.keys(labels)
      .map(
        (key) => `<div class="mini-grade"><span>${labels[key]}</span>
          <div class="mg-bar"><i style="width:${Math.max(2, grades[key])}%;background:${gradeColor(grades[key])}"></i></div>
          <span class="mg-val">${Math.round(grades[key])}</span></div>`
      )
      .join("");
  }

  function tag(text, cls) {
    return `<span class="tag ${cls || ""}">${esc(text)}</span>`;
  }

  function teamBlock(team, data) {
    const players = data.teams[team].player_ids.map((id) => data.players.find((p) => p.id === id));
    const win = data.teams[team].win;
    return `<div class="team-block ${team}">
      <div class="team-title"><span class="dot"></span><span>${TEAM[team]}</span>${win ? '<span class="dim">· победа</span>' : ""}</div>
      <div class="team-heroes">
        ${players
          .map(
            (p) => `<a class="team-player" href="#player-${p.id}" title="${esc(p.hero.name)} — ${esc(p.name)}">
              ${portrait({ ...p.hero, img: p.hero.img }, "team-p")}
              <span class="pname">${esc(p.name)}</span>
            </a>`
          )
          .join("")}
      </div>
    </div>`;
  }

  function sectionHead(title, subtitle) {
    return `<div class="section-head"><div><h2>${esc(title)}</h2>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div></div>`;
  }

  function cardPoint(data) {
    const p = data.verdict.main_point;
    if (!p) return "";
    return `<div class="card verdict-point">
      <h3><svg class="icon"><use href="#i-bolt"/></svg>Переломный момент</h3>
      <div class="point-time">${esc(p.time)}</div>
      <div class="point-title">${esc(p.title)}</div>
      <p class="point-text">${esc(p.text)}</p>
      <div class="point-prob"><span>${p.beneficiary === "radiant" ? "Radiant" : "Dire"}</span><b>${Math.round(p.prob_before)}%</b><span class="prob-arrow">→</span><b>${Math.round(p.prob_after)}%</b></div>
    </div>`;
  }

  function renderVerdict(data) {
    const c = data.verdict.culprit;
    const m = data.verdict.mvp;
    const ring = window.OTACharts.ring(c.blame, "#e2564f");
    return `<div class="verdict-grid">
      <div class="card verdict-culprit">
        <h3><svg class="icon"><use href="#i-skull"/></svg>Главный виновник</h3>
        <div class="culprit-top">
          ${portrait({ ...c, name: c.hero, img: c.img, attr_color: "#e2564f" }, "culprit-p")}
          <div class="culprit-info">
            <div class="big-name">${esc(c.hero)}</div>
            <div class="sub-name">${esc(c.name)} · ${esc(c.position_label)} · ${esc(TEAM[data.match.loser])}</div>
            <div class="sub-name" style="margin-top:4px;color:#f0a9a4">${esc(c.headline)}</div>
          </div>
          <div class="blame-ring">${ring}<div class="ring-share">${Math.round(c.share)}% ответственности</div></div>
        </div>
        <ul class="culprit-bullets">${c.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
      </div>
      <div class="card verdict-mvp">
        <h3><svg class="icon"><use href="#i-trophy"/></svg>Лучший игрок</h3>
        <div class="culprit-top">
          ${portrait({ ...m, name: m.hero, img: m.img, attr_color: "#d9a441" }, "mvp-p")}
          <div class="culprit-info">
            <div class="big-name">${esc(m.hero)}</div>
            <div class="sub-name">${esc(m.name)} · ${esc(m.position_label)}</div>
            <div class="sub-name" style="margin-top:4px;color:var(--gold-2)">KDA ${m.kda.toFixed(2)} · вклад ${Math.round(m.share)}%</div>
          </div>
        </div>
        <ul class="mvp-bullets">${m.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
      </div>
      ${cardPoint(data)}
    </div>`;
  }

  function renderInsight(data) {
    const v = data.verdict;
    const choke = v.choke
      ? `<div class="choke">Камбэк-тревога: <b>${TEAM[v.choke.team]}</b> имели ${Math.round(v.choke.peak)}% на ${esc(v.choke.peak_time)}, но к ${Math.round(v.choke.collapse_minute)}-й минуте осталось меньше 25%.</div>`
      : "";
    return `<div class="insight">
      <div class="insight-label">Вердикт</div>
      <div><p>${v.summary.map((s) => esc(s)).join(" ")}</p>${choke}</div>
    </div>`;
  }

  function renderChart(data) {
    return `<div class="card chart-card" id="chart-section">
      <div class="chart-head">
        <div><h2>График игры</h2><p>Преимущество по минутам. Метки — переломные моменты из разбора.</p></div>
        <div class="seg" id="chart-tabs">
          <button data-metric="gold" class="active">Золото</button>
          <button data-metric="xp">Опыт</button>
          <button data-metric="prob">Шансы</button>
        </div>
      </div>
      <div class="chart-wrap" id="chart-wrap"><svg role="img" aria-label="График преимущества"></svg><div class="chart-tip" hidden></div></div>
      <div class="chart-foot">
        <div class="legend"><span><i class="r"></i>Radiant</span><span><i class="d"></i>Dire</span><span><i class="g"></i>перелом</span></div>
        <div>Наведите на график, чтобы увидеть события минуты</div>
      </div>
      <div class="phases">
        ${data.phases
          .map(
            (p) => `<div class="phase">
              <div class="phase-top"><span>${esc(p.name)}</span><span>${p.start}–${p.end} мин</span></div>
              <h4 class="${p.gold_delta >= 0 ? "phase-gold up" : "phase-gold down"}">${signed(p.gold_delta)} золота</h4>
              <p>${esc(p.comment)}</p>
            </div>`
          )
          .join("")}
      </div>
    </div>`;
  }

  function mapFrame() {
    return `<defs>
        <pattern id="mapGrid" width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M 10 0 L 0 0 0 10" fill="none" stroke="rgba(255,255,255,.04)" stroke-width=".3"/>
        </pattern>
      </defs>
      <rect width="100" height="100" fill="#080b10"/>
      <image href="/img/dota_map.webp" x="0" y="0" width="100" height="100" preserveAspectRatio="xMidYMid slice" opacity=".78"/>
      <rect width="100" height="100" fill="rgba(5,8,12,.22)"/>
      <rect width="100" height="100" fill="url(#mapGrid)"/>`;
  }

  function renderMaps(data) {
    const fights = data.fight_map || [];
    const wards = data.wards || [];
    if (!fights.length && !wards.length) return "";
    const bounds = data.map_bounds || { min: 64, max: 192 };
    const inset = 6.25;
    const norm = (value) => inset + Math.max(0, Math.min(1, (value - bounds.min) / (bounds.max - bounds.min))) * (100 - inset * 2);
    const normY = (value) => 100 - norm(value);
    const duration = data.match.duration || 0;
    const clock = (sec) => `${Math.floor(sec / 60)}:${String(Math.max(0, Math.round(sec % 60))).padStart(2, "0")}`;

    const fightDots = fights
      .map(
        (d) => `<g class="death-marker ${d.team}" transform="translate(${norm(d.x)},${normY(d.y)})" data-time="${d.time}">
          <circle class="death-ring" r="2.7"></circle>
          ${d.victim_img ? `<image href="${esc(d.victim_img)}" x="-2.2" y="-2.2" width="4.4" height="4.4" preserveAspectRatio="xMidYMid slice"></image>` : ""}
          <title>${esc(d.time_label)} · ${esc(d.victim)}${d.killer ? " ← " + esc(d.killer) : ""}${d.fight_winner ? " · драка за " + (d.fight_winner === "radiant" ? "Свет" : d.fight_winner === "dire" ? "Тьму" : "ничью") : ""}</title>
        </g>`
      )
      .join("");
    const fightGroups = {};
    fights.forEach((d) => {
      if (d.fight_index == null) return;
      const group = fightGroups[d.fight_index] || (fightGroups[d.fight_index] = { x: 0, y: 0, n: 0, winner: d.fight_winner, time: d.time_label, t: d.time });
      group.x += norm(d.x);
      group.y += normY(d.y);
      group.n += 1;
      group.t = Math.min(group.t, d.time);
    });
    const fightHalos = Object.values(fightGroups)
      .map((g) => {
        const cx = g.x / g.n;
        const cy = g.y / g.n;
        const winner = g.winner === "radiant" ? "R" : g.winner === "dire" ? "D" : "·";
        return `<g class="fight-halo ${g.winner || ""}" transform="translate(${cx},${cy})" data-time="${g.t}">
          <circle r="${Math.min(9, 3.5 + g.n * 1.1)}"></circle>
          <text y="1">${winner}</text>
          <title>Драка ${esc(g.time)} · победа ${g.winner === "radiant" ? "Света" : g.winner === "dire" ? "Тьмы" : "ничья"}</title>
        </g>`;
      })
      .join("");
    const wardDots = wards
      .map(
        (w) => `<g class="ward-marker ${w.type} ${w.team}" transform="translate(${norm(w.x)},${normY(w.y)})" data-time="${w.time}">
          <circle class="ward-ring" r="${w.type === "observer" ? 2.9 : 2.5}"></circle>
          <image href="/img/items/ward_${w.type}.png" x="-2.1" y="-2.1" width="4.2" height="4.2" preserveAspectRatio="xMidYMid slice"></image>
          <title>${esc(w.time_label)} · ${w.type === "observer" ? "обс" : "сентри"} · ${esc(w.hero)}${w.duration ? " · " + Math.round(w.duration / 60) + " мин" : ""}</title>
        </g>`
      )
      .join("");
    const buildingDots = (data.buildings || [])
      .map((b) => {
        const shape =
          b.kind === "tower"
            ? `<path d="M0 -1.7 L1.7 0 L0 1.7 L-1.7 0 Z"></path>`
            : b.kind === "rax"
              ? `<rect x="-1.2" y="-1.2" width="2.4" height="2.4" rx=".3"></rect>`
              : `<circle r="1.5"></circle>`;
        return `<g class="building ${b.team} ${b.kind} ${b.destroyed ? "destroyed" : ""}" transform="translate(${norm(b.x)},${normY(b.y)})">
          ${shape}
          <title>${esc(b.label)} · ${b.destroyed ? "разрушено" : "стоит"}</title>
        </g>`;
      })
      .join("");

    return `<section class="section" id="map">
      ${sectionHead("Карта", "Карта Dota 2 (Dota 2 Wiki) с точками смертей в драках и вардов. Наведите на точку, чтобы увидеть тайминг и героя.")}
      <div class="map-grid">
        <div class="map-card">
          <div class="map-head"><h3>Карта драк</h3><span class="map-legend"><i class="rad"></i>Свет <i class="dir"></i>Тьма <i class="win"></i>R/D — победа драки</span></div>
          <div class="map-wrap"><svg viewBox="0 0 100 100" class="map-svg" role="img" aria-label="Карта смертей в драках">${mapFrame()}${buildingDots}${fightHalos}${fightDots}</svg></div>
          <div class="map-controls"><input type="range" min="0" max="${duration}" value="${duration}" class="map-range" aria-label="Время карты драк"><span class="map-now">${clock(duration)}</span><span class="map-count">${fights.length} смертей</span></div>
          <div class="intel-note">Иконки героев — кто погиб; R/D в круге — кто выиграл драку. Ромбы и квадраты — вышки, бараки и трон.</div>
        </div>
        <div class="map-card">
          <div class="map-head"><h3>Карта вардов</h3><span class="map-legend"><i class="obs"></i>обс <i class="sen"></i>сентри</span></div>
          <div class="map-wrap"><svg viewBox="0 0 100 100" class="map-svg" role="img" aria-label="Карта вардов">${mapFrame()}${buildingDots}${wardDots}</svg></div>
          <div class="map-controls"><input type="range" min="0" max="${duration}" value="${duration}" class="map-range" aria-label="Время карты вардов"><span class="map-now">${clock(duration)}</span><span class="map-count">${wards.length} вардов</span></div>
          <div class="intel-note">Обсы и сентри — иконками, обводка зелёная/красная по команде. Тёмные вышки и бараки — уже снесены.</div>
        </div>
      </div>
    </section>`;
  }

  function renderBlame(data) {
    const loser = data.match.loser;
    const rows = data.players
      .filter((p) => p.team === loser)
      .sort((a, b) => b.blame - a.blame);
    const credits = data.players
      .filter((p) => p.team !== loser)
      .sort((a, b) => b.credit - a.credit);
    const least = data.verdict.least;
    return `<section class="section" id="blame">
      ${sectionHead("Кто виноват", `Индекс вины для проигравшей команды ${TEAM[loser]}: экономика, смерти, бой, вижн, объекты и дисциплина с ролевыми весами.`)}
      <div class="grid-2">
        <div class="panel">
          <div class="blame-list">
            ${rows
              .map(
                (p, i) => `<details class="blame-row" ${i === 0 ? "open" : ""}>
                  <summary>
                    <span class="blame-rank">${i + 1}</span>
                    ${portrait({ ...p.hero, img: p.hero.img, attr_color: p.hero.attr_color }, "mistake-p")}
                    <span class="blame-hero"><b>${esc(p.hero.name)}</b><span>${esc(p.name)} · ${esc(p.position_label)} · ${p.deaths} ${plural(p.deaths, "смерть", "смерти", "смертей")}</span></span>
                    <span class="blame-bar"><i style="width:${Math.max(3, p.blame)}%"></i></span>
                    <span class="blame-index">${Math.round(p.blame)}<small>индекс</small></span>
                    <span class="blame-share"><b>${Math.round(p.blame_share)}%</b>вина</span>
                  </summary>
                  <div class="blame-detail">
                    <div>${gradeRows(p.grades)}</div>
                    <ul class="blame-reasons">
                      <li>${p.deaths} ${plural(p.deaths, "смерть", "смерти", "смертей")} (${p.deaths10.toFixed(1)}/10 мин), цена смертей ≈ ${fmt(p.death_cost)}; без размена — ${p.solos}.</li>
                      <li>${fmt(p.gpm)} GPM, ${fmt(p.networth)} нетворса (${p.nw_share}% команды), ${p.lh10} ЛХ к 10-й минуте.</li>
                      <li>${fmt(p.hero_damage)} урона по героям (${fmt(p.hd_min)}/мин), участие в драках ${p.tf_part}%, KDA ${p.kda.toFixed(2)}.</li>
                      ${p.solos || p.throws ? `<li>Ошибки: ${p.solos} ${plural(p.solos, "смерть", "смерти", "смертей")} без размена, ${p.throws} при преимуществе, ${p.buyback_deaths} после байбека.</li>` : ""}
                    </ul>
                  </div>
                </details>`
              )
              .join("")}
          </div>
          <div class="least-note"><b>${esc(least.hero)}</b> — ${esc(least.text)}</div>
        </div>
        <div class="panel">
          <h3>Заслуги победителей</h3>
          <div class="credit-list">
            ${credits
              .map(
                (p) => `<div class="credit-row">
                  ${portrait({ ...p.hero, img: p.hero.img, attr_color: p.hero.attr_color }, "mistake-p")}
                  <div><b>${esc(p.hero.name)}</b><span>${esc(p.name)} · ${esc(p.position_label)} · ${p.kills}/${p.deaths}/${p.assists}</span></div>
                  <div class="cr-val">${Math.round(p.credit)}<small>${Math.round(p.credit_share)}%</small></div>
                </div>`
              )
              .join("")}
          </div>
          <div style="margin-top:14px;font-size:11px;color:var(--dim);line-height:1.55">Вклад считается по тем же шести категориям, но со знаком «плюс»: чем выше — тем больше игрок сделал для победы.</div>
        </div>
      </div>
    </section>`;
  }

  function renderPlayers(data) {
    return `<section class="section" id="players">
      <div class="section-head">
        <div><h2>Игроки</h2><p>Полная карточка: экономика, бой, вижн, предметы, смерти и оценки по шести категориям.</p></div>
        <div class="team-tabs" id="team-tabs">
          <button data-team="all" class="active">Все</button>
          <button data-team="radiant">Radiant</button>
          <button data-team="dire">Dire</button>
        </div>
      </div>
      <div class="players-grid" id="players-grid">
        ${data.players.map(playerCard).join("")}
      </div>
    </section>`;
  }

  function playerCard(p) {
    const mistakes = (state.data.mistakes || []).filter((m) => m.player_id === p.id);
    const deathRows = (p.death_log || [])
      .map(
        (d) => `<tr><td>${esc(d.time_label)}</td><td>${esc(d.killer)}</td><td>${fmt(d.cost)}</td><td>${d.time_dead} с</td><td class="${d.solo ? "solo" : ""}">${d.solo ? "без размена" : "—"}</td></tr>`
      )
      .join("");
    return `<article class="player-card ${p.team}" id="player-${p.id}" data-team="${p.team}">
      <div class="pc-head">
        ${portrait({ ...p.hero, img: p.hero.img, attr_color: p.hero.attr_color }, "")}
        <div class="pc-title">
          <h3>${esc(p.hero.name)}</h3>
          <div class="pc-player">${esc(p.name)} · ${esc(p.lane)} линия</div>
          <div class="pc-tags">${tag(p.position_label, "pos")}${tag(TEAM[p.team], p.team === "radiant" ? "rad" : "dir")}${tag(p.hero.attr_label)}${p.rank && p.rank.label !== "—" ? tag(p.rank.label, "rank") : ""}</div>
        </div>
        <div class="pc-kda"><div class="kda">${p.kills}<span class="dim"> / </span>${p.deaths}<span class="dim"> / </span>${p.assists}</div><small>KDA ${p.kda.toFixed(2)} · KP ${p.kp}%</small></div>
      </div>
      <div class="pc-stats">
        <div><b>${fmt(p.gpm)}</b><span>GPM</span></div>
        <div><b>${fmt(p.xpm)}</b><span>XPM</span></div>
        <div><b>${fmt(p.networth)}</b><span>Нетворс</span></div>
        <div><b>${p.lh10}<span class="dim">/${p.dn10}</span></b><span>ЛХ/ДН 10м</span></div>
        <div><b>${fmt(p.hero_damage)}</b><span>Урон</span></div>
        <div><b>${fmt(p.tower_damage)}</b><span>По зданиям</span></div>
        <div><b>${p.tf_part}%</b><span>В драках</span></div>
        <div><b>${p.obs + p.sen}</b><span>Варды</span></div>
      </div>
      <div class="pc-body">
        <div class="pc-chart-row">
          <div class="mini-grades">${miniGrades(p.grades)}</div>
          <svg class="pc-radar" data-pid="${p.id}" aria-hidden="true"></svg>
        </div>
        <div class="items">
          ${p.items.map((item) => `<img class="item" src="${esc(item.img)}" alt="${esc(item.name)}" title="${esc(item.name)}" loading="lazy" onerror="this.remove()">`).join("")}
          ${p.neutral_item ? `<img class="item neutral" src="${esc(p.neutral_item.img)}" alt="${esc(p.neutral_item.name)}" title="${esc(p.neutral_item.name)}" loading="lazy" onerror="this.remove()">` : ""}
        </div>
        <div class="pc-notes">
          <span class="note-chip">Вижн ${p.obs}/${p.sen}</span>
          <span class="note-chip">Деварды ${p.dewards}</span>
          <span class="note-chip">Стаки ${p.stacks}</span>
          <span class="note-chip">Мудрость ${p.wisdom || 0}</span>
          <span class="note-chip">Байбеки ${p.buybacks}</span>
          ${p.notes.map((n) => `<span class="note-chip">${esc(n)}</span>`).join("")}
        </div>
      </div>
      <details class="pc-details">
        <summary><span>Детали: смерти, ошибки, визави</span><span>${p.death_log.length} ${plural(p.death_log.length, "смерть", "смерти", "смертей")} · ${mistakes.length} ${plural(mistakes.length, "ошибка", "ошибки", "ошибок")}</span></summary>
        <div class="details-body">
          <div class="checkpoint-row">
            ${(p.checkpoints || []).map((c) => `<span><b>${c.minute} мин</b> ${fmt(c.nw)} NW · ${c.lh} LH</span>`).join("")}
          </div>
          ${p.benchmarks && Object.keys(p.benchmarks).length ? `<div class="benchmark-row">Бенчмарк героя: ${Object.values(p.benchmarks).map((b) => `${b.label} ${b.pct}-й`).join(" · ")}</div>` : ""}
          ${deathRows ? `<table class="death-table"><thead><tr><th>Время</th><th>Убийца</th><th>Цена</th><th>Мёртв</th><th>Тип</th></tr></thead><tbody>${deathRows}</tbody></table>` : '<div class="empty">Смертей нет.</div>'}
          ${mistakes.length ? `<div class="mini-mistakes">${mistakes.map((m) => `<div class="mini-mistake"><span class="sev-dot sev-${m.severity}"></span><span><b>${esc(m.time_label)} ${esc(m.title)}</b> — ${esc(m.text)}</span></div>`).join("")}</div>` : ""}
          <div class="mini-mistakes">
            ${p.rival ? `<div class="mini-mistake"><span class="sev-dot sev-2"></span><span><b>Визави ${esc(p.rival.hero)}</b> — нетворс ${signed(p.rival.nw_diff)}, GPM ${signed(p.rival.gpm_diff)}, ЛХ@10 ${signed(p.rival.lh10_diff)}, урон ${signed(p.rival.hd_diff)}.</span></div>` : ""}
          </div>
        </div>
      </details>
    </article>`;
  }

  function renderMistakes(data) {
    const rows = data.mistakes || [];
    return `<section class="section" id="mistakes">
      <div class="section-head">
        <div><h2>Ошибки и цена</h2><p>Автоматические эвристики по событиям: смерти без размена, дорогие смерти, байбеки, потерянные объекты, провал вижна. Severity — важность.</p></div>
        <div class="filters" id="mistake-filters">
          <button class="chip active" data-team="all">Все</button>
          <button class="chip" data-team="radiant">Radiant</button>
          <button class="chip" data-team="dire">Dire</button>
        </div>
      </div>
      <div class="mistakes-legend"><span class="sev-dot sev-5"></span> решающе <span class="sev-dot sev-4"></span> критично <span class="sev-dot sev-3"></span> серьёзно <span class="sev-dot sev-2"></span> заметно <span class="sev-dot sev-1"></span> мелочь</div>
      <div class="mistakes-list" id="mistakes-list">
        ${rows
          .map((m) => {
            const p = data.players.find((x) => x.id === m.player_id);
            const hero = p ? p.hero : { name: m.team === "radiant" ? "Radiant" : "Dire", img: "", attr_color: "#d9a441" };
            const labels = { 5: "решающе", 4: "критично", 3: "серьёзно", 2: "заметно", 1: "мелочь" };
            return `<div class="mistake s${m.severity}" data-team="${m.team}">
              <div class="m-time">${esc(m.time_label)}</div>
              ${portrait({ ...hero, img: hero.img || "", attr_color: hero.attr_color || "#d9a441" }, "mistake-p")}
              <div class="m-body">
                <b>${esc(m.title)}</b>
                <div class="m-meta">${p ? esc(p.hero.name) + " · " + esc(p.name) + " · " + esc(p.position_label) : esc(TEAM[m.team])}${p ? " · " + p.kills + "/" + p.deaths + "/" + p.assists : ""}</div>
                <p>${esc(m.text)}</p>
              </div>
              <div class="m-cost"><span class="sev-label">${labels[m.severity]}</span>${m.cost ? `<b>${fmt(m.cost)}</b><span>золота</span>` : "<b>—</b>"}</div>
            </div>`;
          })
          .join("") || '<div class="empty">Ошибок не найдено — либо матч чистый, либо данных мало.</div>'}
      </div>
      ${data.team_mistakes && data.team_mistakes.length ? `<div class="team-mistakes">${data.team_mistakes.map((m) => `<div class="team-mistake"><b>${esc(TEAM[m.team])} · ${esc(m.title)}</b><p>${esc(m.text)}</p></div>`).join("")}</div>` : ""}
    </section>`;
  }

  function renderMoments(data) {
    const points = data.turning_points || [];
    if (!points.length) return "";
    return `<section class="section" id="moments">
      ${sectionHead("Переломные моменты", "Окна по 2–3 минуты, где вероятность победы менялась сильнее всего.")}
      <div class="panel">
        <div class="moments">
          ${points
            .map(
              (p) => `<div class="moment">
                <div class="moment-time">${esc(p.time)}</div>
                <span class="moment-dot"></span>
                <div class="moment-card">
                  <h4>${esc(p.title)} · ${esc(TEAM[p.beneficiary])}</h4>
                  <p>${esc(p.text)}</p>
                  <div class="moment-meta">
                    <span>Шансы: <b>${Math.round(p.prob_before)}%</b> → <b class="${p.delta_prob >= 0 ? "up" : "down"}">${Math.round(p.prob_after)}%</b></span>
                    <span>Золото: <b class="${p.gold_swing >= 0 ? "up" : "down"}">${signed(p.gold_swing)}</b></span>
                    <span>Сила: <b>${p.severity.toFixed(1)} п.п.</b></span>
                  </div>
                </div>
              </div>`
            )
            .join("")}
        </div>
      </div>
    </section>`;
  }

  function renderCompare(data) {
    const rs = data.teams.radiant.stats;
    const ds = data.teams.dire.stats;
    const rows = [
      ["Убийства", rs.kills, ds.kills, (v) => v],
      ["Смерти", rs.deaths, ds.deaths, (v) => v],
      ["Башни", rs.towers, ds.towers, (v) => v],
      ["Рошаны", rs.roshans, ds.roshans, (v) => v],
      ["Нетворс", rs.networth, ds.networth, (v) => fmt(v)],
      ["Урон по героям", rs.hero_damage, ds.hero_damage, (v) => fmt(v)],
      ["Варды", rs.obs + rs.sen, ds.obs + ds.sen, (v) => v],
      ["Деварды", rs.dewards, ds.dewards, (v) => v],
      ["Драки", `${rs.fight_wins}:${rs.fight_losses}`, `${ds.fight_wins}:${ds.fight_losses}`, (v) => v],
      ["Контроль", rs.control + "%", ds.control + "%", (v) => v],
    ];
    return `<div class="panel">
      <h3>Командная статистика</h3>
      <div class="compare">
        ${rows
          .map(([label, l, r, f]) => {
            const ln = typeof l === "number" ? l : parseFloat(l) || 0;
            const rn = typeof r === "number" ? r : parseFloat(r) || 0;
            const total = Math.max(1, ln + rn);
            return `<div class="cmp-row">
              <span class="val l">${esc(f(l))}</span>
              <div class="cmp-bar l"><i style="width:${(ln / total) * 100}%"></i></div>
              <span class="lbl">${esc(label)}</span>
              <div class="cmp-bar r"><i style="width:${(rn / total) * 100}%"></i></div>
              <span class="val r">${esc(f(r))}</span>
            </div>`;
          })
          .join("")}
      </div>
    </div>`;
  }

  function renderLanes(data) {
    return `<div class="panel">
      <h3>Лейнинг</h3>
      <div class="lanes">
        ${data.lanes
          .map((l) => {
            const a = data.players.find((p) => p.id === l.a_core);
            const b = data.players.find((p) => p.id === l.b_core);
            const cls = l.winner === "draw" ? "even" : l.winner === "radiant" ? "up" : "down";
            return `<div class="lane-row">
              <div><h4>${esc(l.title)}</h4><p>${esc(a.hero.name)} ${l.a_lh10} ЛХ · ${fmt(l.a_nw10)} нетворса
                <span class="dim">vs</span> ${esc(b.hero.name)} ${l.b_lh10} ЛХ · ${fmt(l.b_nw10)} нетворса</p></div>
              <div class="lane-diff ${cls}">${signed(l.diff)}<small>${l.winner === "draw" ? "ровно" : TEAM[l.winner] + " сильнее"}</small></div>
            </div>`;
          })
          .join("")}
      </div>
    </div>`;
  }

  function renderExtras(data) {
    const cards = [];
    if ((data.wisdom_runes || []).length) cards.push(renderWisdom(data));
    if ((data.chat || []).length) cards.push(renderChat(data));
    else cards.push(`<div class="intel-card chat-card">
      <div class="intel-head"><h3>Чат матча</h3><span>нет сообщений</span></div>
      <div class="empty">В этом реплее чат не записан — сервер не сохранил сообщения. Это не ошибка отчёта.</div>
      <div class="intel-note">Если в матче был чат, но его нет здесь — значит, его не было в файле реплея.</div>
    </div>`);
    if ((data.glyphs || []).length) cards.push(renderGlyphs(data));
    if (!cards.length) return "";
    return `<section class="section" id="extras">
      ${sectionHead("Дополнительно", "Руны мудрости, чат, глифы и культура игроков — всё, что удалось вытащить из реплея.")}
      <div class="intel-grid">${cards.join("")}</div>
    </section>`;
  }

  function renderWisdom(data) {
    const rows = data.wisdom_runes || [];
    const rad = rows.filter((r) => r.team === "radiant").length;
    const dire = rows.filter((r) => r.team === "dire").length;
    return `<div class="intel-card rune-card">
      <div class="intel-head"><h3>Руны мудрости</h3><span>${rows.length} ${plural(rows.length, "пик", "пика", "пиков")}</span></div>
      <div class="rune-score">
        <div><b class="rad">${rad}</b><span>Силы Света</span></div>
        <i>:</i>
        <div><b class="dir">${dire}</b><span>Силы Тьмы</span></div>
      </div>
      <div class="rune-list">
        ${rows.length
          ? rows.slice(0, 16).map((r) => `<div class="rune-row ${r.team}"><span class="dot"></span><span class="rune-time">${esc(r.time_label)}</span><span class="rune-hero">${esc(r.hero || "—")}</span><span class="rune-player">${esc(r.name || "")}</span></div>`).join("")
          : '<div class="empty">В логе нет пиков рун мудрости.</div>'}
      </div>
      <div class="intel-note">Первая руна — на 7:00, дальше каждые 7 минут. Считаем по ключу 8 в логе рун.</div>
    </div>`;
  }

  function renderChat(data) {
    const rows = data.chat || [];
    return `<div class="intel-card chat-card">
      <div class="intel-head"><h3>Чат матча</h3><span>${rows.length} сообщений</span></div>
      <div class="chat-toolbar">
        <div class="seg" id="chat-filters">
          <button data-team="all" class="active">Все</button>
          <button data-team="radiant">Свет</button>
          <button data-team="dire">Тьма</button>
        </div>
      </div>
      <div class="chat-log" id="chat-log">
        ${rows.length
          ? rows.slice(0, 200).map((c) => `<div class="chat-line ${c.team || ""}" data-team="${c.team || ""}">
              <span class="chat-time">${esc(c.time_label)}</span>
              <span class="chat-author">${esc(c.hero || "?")}<small>${esc(c.name || "")}</small></span>
              <span class="chat-text">${esc(c.type === "chatwheel" ? "Чат-колесо" : c.text)}</span>
            </div>`).join("")
          : '<div class="empty">В реплее нет текстового чата.</div>'}
      </div>
      <div class="intel-note">Текст из реплея. Оскорбления и спам — не модерация, а просто лог.</div>
    </div>`;
  }

  function renderGlyphs(data) {
    const rows = data.glyphs || [];
    const rad = rows.filter((r) => r.team === "radiant").length;
    const dire = rows.filter((r) => r.team === "dire").length;
    return `<div class="intel-card glyph-card">
      <div class="intel-head"><h3>Глифы</h3><span>${rows.length ? rows.length + " событий" : "нет данных"}</span></div>
      ${rows.length
        ? `<div class="glyph-score"><b class="rad">${rad}</b><span>Силы Света</span><b class="dir">${dire}</b><span>Силы Тьмы</span></div>
           <div class="glyph-list">${rows.map((g) => `<div class="glyph-row"><span class="dot ${g.team}"></span><span>${esc(g.time_label)}</span><span>${esc(g.hero || (g.team === "radiant" ? "Силы Света" : "Силы Тьмы"))}</span></div>`).join("")}</div>`
        : `<div class="empty">Публичный API и парсер реплея не отдают события глифа. Сколько их было в матче — по этим данным не узнать.</div>`}
      <div class="intel-note">Глиф — командная способность; отдельного события активации в публичном API нет.</div>
    </div>`;
  }

  function renderFights(data) {
    const rows = (data.fights || []).filter((f) => f.major || f.radiant_deaths + f.dire_deaths > 0);
    if (!rows.length) return "";
    return `<section class="section" id="fights">
      ${sectionHead("Драки", "Командные бои по данным парсера: счёт, размен золота и лучший игрок.")}
      <div class="table-wrap">
        <table class="fights">
          <thead><tr><th>Время</th><th>Победитель</th><th>Счёт</th><th>Золото</th><th>Урон</th><th>Лучший игрок</th><th>Ключевые смерти</th></tr></thead>
          <tbody>
            ${rows
              .map(
                (f) => `<tr>
                  <td class="time">${esc(f.time)}</td>
                  <td><span class="fight-win ${f.winner}">${f.winner === "draw" ? "Ничья" : TEAM[f.winner]}</span></td>
                  <td class="tnum">${f.radiant_deaths}:${f.dire_deaths}</td>
                  <td class="tnum" style="color:${(f.winner === "dire" ? -f.gold_swing : f.gold_swing) >= 0 ? "#6fd48d" : "#f07972"}">${signed(f.winner === "dire" ? -f.gold_swing : f.gold_swing)}</td>
                  <td class="tnum">${fmt(f.damage_radiant + f.damage_dire)}</td>
                  <td><span class="fight-mvp"><img src="${esc(f.mvp.img)}" alt="" loading="lazy" onerror="this.remove()">${esc(f.mvp.hero)} · ${fmt(f.mvp.damage)}</span></td>
                  <td>${f.deaths.slice(0, 2).map((d) => `<span class="dim">${esc(d.victim)}</span>`).join(", ")}${f.deaths.length > 2 ? ` <span class="dim">+${f.deaths.length - 2}</span>` : ""}</td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </section>`;
  }

  function renderDraft(data) {
    const d = data.draft;
    if (!d || (!d.picks.length && !d.bans.length)) return "";
    const team = (t) => {
      const picks = d.picks.filter((p) => p.team === t);
      const bans = d.bans.filter((p) => p.team === t);
      const comp = d.composition[t];
      return `<div class="draft-team ${t}">
        <h3>${TEAM[t]} · пики</h3>
        <div class="pick-list">
          ${picks
            .map(
              (p, idx) => `<div class="pick"><span class="order">${idx + 1}</span><img src="${esc(p.hero.img)}" alt="" onerror="this.remove()"><span>${esc(p.hero.name)}</span><span class="roles">${esc((p.hero.roles || []).slice(0, 2).join(" · "))}</span></div>`
            )
            .join("")}
        </div>
        <div class="comp-chips">
          <span class="comp-chip">${comp.melee} мили / ${comp.ranged} ренж</span>
          <span class="comp-chip">${comp.disablers} с контролем</span>
          <span class="comp-chip">${comp.initiators} инициаторов</span>
          <span class="comp-chip">${comp.nukers} нюкеров</span>
        </div>
        ${bans.length ? `<div class="bans"><h4>Баны</h4><div class="ban-list">${bans.map((b) => `<img src="${esc(b.hero.img)}" alt="${esc(b.hero.name)}" title="${esc(b.hero.name)}" onerror="this.remove()">`).join("")}</div></div>` : ""}
      </div>`;
    };
    return `<section class="section" id="draft">
      ${sectionHead("Драфт", "Пики, баны и состав по ролям — без глубоких выводов о мете.")}
      <div class="draft-grid">${team("radiant")}${team("dire")}</div>
    </section>`;
  }

  function renderReport(data) {
    const match = data.match;
    const report = $("#report");
    report.innerHTML = `
      <nav class="report-nav" aria-label="Разделы отчёта">
        <a href="#overview">Обзор</a>
        <a href="#chart-section">График</a>
        <a href="#map">Карта</a>
        <a href="#blame">Вина</a>
        <a href="#players">Игроки</a>
        <a href="#mistakes">Ошибки</a>
        <a href="#moments">Моменты</a>
        <a href="#extras">Факты</a>
        <a href="#fights">Драки</a>
        <a href="#draft">Драфт</a>
        <div class="report-actions">
          <button class="btn ghost" id="copy-btn" type="button"><svg class="icon"><use href="#i-copy"/></svg>Ссылка</button>
          <button class="btn ghost" id="download-btn" type="button"><svg class="icon"><use href="#i-download"/></svg>JSON</button>
        </div>
      </nav>
      <section id="overview">
        <div class="match-hero">
          ${teamBlock("radiant", data)}
          <div class="match-center">
            <div class="match-meta"><span>${esc(match.game_mode)}</span><span>·</span><span>${esc(match.duration_label)}</span><span>·</span><span>${esc(match.date)}</span>${match.average_rank && match.average_rank !== "—" ? `<span>·</span><span>${esc(match.average_rank)}${match.average_mmr ? " · " + fmt(match.average_mmr) + " MMR" : ""}</span>` : ""}</div>
            <div class="scoreline"><span class="${match.radiant_win ? "win" : "lose"}">${match.score.radiant}</span><span class="sep">:</span><span class="${match.radiant_win ? "lose" : "win"}">${match.score.dire}</span></div>
            <div class="winner-badge ${match.winner}"><svg class="icon" style="width:12px;height:12px"><use href="#i-trophy"/></svg>${esc(match.winner_word)} побеждает</div>
            <div class="match-sub">Матч <b>${match.id}</b> · первая кровь ${match.first_blood_time ? esc(match.first_blood_time) : "—"} · ${match.lobby}</div>
          </div>
          ${teamBlock("dire", data)}
        </div>
        ${renderVerdict(data)}
        ${renderInsight(data)}
        ${renderChart(data)}
      </section>
      ${renderMaps(data)}
      ${renderBlame(data)}
      ${renderPlayers(data)}
      ${renderMistakes(data)}
      ${renderMoments(data)}
      <section class="section" id="teams">
        ${sectionHead("Команды и линии", "Сравнение по ключевым метрикам и итоги лейнинга.")}
        <div class="grid-2">${renderCompare(data)}${renderLanes(data)}</div>
      </section>
      ${renderExtras(data)}
      ${renderFights(data)}
      ${renderDraft(data)}
    `;
    showReport();
    // mount charts after layout
    requestAnimationFrame(() => {
      mountCharts();
      bindReport();
    });
    document.title = `${match.winner_word} ${match.score.radiant}:${match.score.dire} — разбор матча ${match.id} | OTA`;
  }

  function mountCharts() {
    const data = state.data;
    if (!data) return;
    const wrap = $("#chart-wrap");
    if (wrap) window.OTACharts.advantage(wrap, data, state.metric);
    $$(".pc-radar").forEach((svg) => {
      const p = data.players.find((x) => x.id === svg.dataset.pid);
      if (p) window.OTACharts.radar(svg, p.grades, p.team === "radiant" ? "#4fbf73" : "#e2564f");
    });
    if (window.ResizeObserver) {
      if (state.observer) state.observer.disconnect();
      state.observer = new ResizeObserver(() => {
        clearTimeout(state.chartTimer);
        state.chartTimer = setTimeout(() => {
          const w = $("#chart-wrap");
          if (w) window.OTACharts.advantage(w, state.data, state.metric);
        }, 90);
      });
      if (wrap) state.observer.observe(wrap);
    }
  }

  function bindReport() {
    const data = state.data;
    $$("#chart-tabs button").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.metric = btn.dataset.metric;
        $$("#chart-tabs button").forEach((b) => b.classList.toggle("active", b === btn));
        const wrap = $("#chart-wrap");
        if (wrap) window.OTACharts.advantage(wrap, data, state.metric);
      });
    });
    $$("#team-tabs button").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.team = btn.dataset.team;
        $$("#team-tabs button").forEach((b) => b.classList.toggle("active", b === btn));
        $$("#players-grid .player-card").forEach((card) => {
          card.hidden = state.team !== "all" && card.dataset.team !== state.team;
        });
      });
    });
    $$("#mistake-filters .chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.mistakeTeam = btn.dataset.team;
        $$("#mistake-filters .chip").forEach((b) => b.classList.toggle("active", b === btn));
        $$("#mistakes-list .mistake").forEach((row) => {
          row.hidden = state.mistakeTeam !== "all" && row.dataset.team !== state.mistakeTeam;
        });
      });
    });
    $$("#chat-filters button").forEach((btn) => {
      btn.addEventListener("click", () => {
        $$("#chat-filters button").forEach((b) => b.classList.toggle("active", b === btn));
        $$("#chat-log .chat-line").forEach((row) => {
          row.hidden = btn.dataset.team !== "all" && row.dataset.team !== btn.dataset.team;
        });
      });
    });
    $$(".map-range").forEach((input) => {
      input.addEventListener("input", () => {
        const card = input.closest(".map-card");
        const limit = Number(input.value);
        card.querySelectorAll("[data-time]").forEach((dot) => {
          dot.style.display = Number(dot.dataset.time) <= limit ? "" : "none";
        });
        const label = card.querySelector(".map-now");
        if (label) label.textContent = `${Math.floor(limit / 60)}:${String(Math.round(limit % 60)).padStart(2, "0")}`;
      });
    });
    const copy = $("#copy-btn");
    if (copy) copy.addEventListener("click", copyLink);
    const dl = $("#download-btn");
    if (dl) dl.addEventListener("click", downloadJson);
    $$('#report a[href^="#"]').forEach((link) => {
      link.addEventListener("click", (event) => {
        const id = link.getAttribute("href").slice(1);
        const target = document.getElementById(id);
        if (!target) return;
        event.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  async function copyLink() {
    const url = `${location.origin}${location.pathname}#match=${state.data.match.id}`;
    try {
      await navigator.clipboard.writeText(url);
      toast("Ссылка скопирована");
    } catch {
      toast(url);
    }
  }

  function downloadJson() {
    const blob = new Blob([JSON.stringify(state.data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `ota-match-${state.data.match.id}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
    toast("JSON отчёта скачан");
  }

  /* ------------------------------------------------------------ data flow */
  function stopPolling() {
    clearTimeout(state.pollTimer);
    clearInterval(state.elapsedTimer);
    state.pollTimer = 0;
    state.elapsedTimer = 0;
  }

  function hideProgress() {
    $("#progress-panel").hidden = true;
    $("#progress-panel").classList.remove("is-error");
  }

  function showLanding() {
    stopPolling();
    hideProgress();
    $("#landing").hidden = false;
    $("#report").hidden = true;
    $("#loading").hidden = true;
    $("#error-panel").hidden = true;
    if (window.scrollY > 40) window.scrollTo({ top: 0 });
    document.title = "OTA — разбор матчей Dota 2: виновники, ошибки, переломные моменты";
  }

  function showLoading() {
    stopPolling();
    hideProgress();
    $("#landing").hidden = true;
    $("#report").hidden = true;
    $("#error-panel").hidden = true;
    $("#loading").hidden = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function showReport() {
    hideProgress();
    $("#landing").hidden = true;
    $("#loading").hidden = true;
    $("#error-panel").hidden = true;
    $("#report").hidden = false;
    window.scrollTo({ top: 0 });
  }

  function showError(message) {
    stopPolling();
    hideProgress();
    $("#landing").hidden = true;
    $("#loading").hidden = true;
    $("#report").hidden = true;
    $("#error-panel").hidden = false;
    $("#error-text").textContent = message || "Неизвестная ошибка";
    window.scrollTo({ top: 0 });
  }

  function progressElapsedText() {
    const seconds = Math.max(0, Math.floor((Date.now() - state.progressStartedAt) / 1000));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function tickProgressElapsed() {
    const node = $("#progress-elapsed");
    if (node) node.textContent = progressElapsedText();
  }

  function showProgress(job) {
    $("#landing").hidden = true;
    $("#report").hidden = true;
    $("#loading").hidden = true;
    $("#error-panel").hidden = true;
    $("#progress-panel").hidden = false;
    $("#progress-panel").classList.remove("is-error");
    $("#progress-retry").hidden = true;
    state.progressStartedAt = Date.now() - Math.max(0, Number(job.elapsed) || 0) * 1000;
    updateProgressPanel(job);
    clearInterval(state.elapsedTimer);
    state.elapsedTimer = setInterval(tickProgressElapsed, 1000);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateProgressPanel(job) {
    const stages = {
      queued: "В очереди",
      fetch: "Проверяем матч",
      download: "Скачиваем реплей",
      parse: "Парсим реплей",
      stats: "Считаем статистику",
      done: "Готово",
      error: "Ошибка",
    };
    const rank = { queued: 0, fetch: 0, download: 1, parse: 2, stats: 3, done: 4, error: 0 };
    const active = job.status === "done" ? 4 : rank[job.stage] ?? 0;
    const isError = job.status === "error";
    const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
    $("#progress-title").textContent = isError ? "Парс не удался" : job.status === "done" ? "Отчёт готов" : "Готовим разбор матча";
    $("#progress-message").textContent = job.message || stages[job.stage] || "Проверяем матч";
    $("#progress-stage").textContent = stages[job.stage] || "Проверяем матч";
    const bar = $("#progress-bar");
    bar.style.width = progress + "%";
    const track = $("#progress-track");
    track.classList.toggle("indeterminate", !isError && (job.stage === "parse" || job.stage === "queued") && job.status !== "done");
    $$("#progress-steps li").forEach((li, index) => {
      li.classList.toggle("done", job.status === "done" || (!isError && index < active));
      li.classList.toggle("active", !isError && job.status !== "done" && index === active);
    });
    tickProgressElapsed();
  }

  function progressError(job) {
    stopPolling();
    const panel = $("#progress-panel");
    panel.hidden = false;
    panel.classList.add("is-error");
    $("#progress-title").textContent = "Не удалось разобрать матч";
    $("#progress-message").textContent = job.error || "Парсер не смог обработать реплей. Попробуйте ещё раз.";
    $("#progress-stage").textContent = job.code === "replay_expired" ? "Реплей недоступен" : "Ошибка парса";
    $("#progress-bar").style.width = "0%";
    $("#progress-track").classList.remove("indeterminate");
    $("#progress-retry").hidden = !state.replayId || ["replay_expired", "no_replay"].includes(job.code);
    $$("#progress-steps li").forEach((li) => li.classList.remove("active", "done"));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function startReplay(id) {
    stopPolling();
    state.replayId = id;
    state.pollFailures = 0;
    showProgress({ status: "queued", stage: "queued", progress: 2, message: "Запускаем локальный парсер реплея", elapsed: 0 });
    try {
      const response = await fetch("/api/replay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Не удалось запустить парс");
      updateProgressPanel(payload.job);
      pollReplay(id);
    } catch (error) {
      progressError({ error: error.message, code: "start_failed" });
    }
  }

  function pollReplay(id) {
    const poll = async () => {
      try {
        const response = await fetch(`/api/replay/${id}`);
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "Задача парса не найдена");
        const job = payload.job;
        if (job.status === "done" && job.analysis) {
          stopPolling();
          setData(job.analysis, { hash: `#match=${id}` });
          return;
        }
        updateProgressPanel(job);
        if (job.status === "error") {
          progressError(job);
          return;
        }
        state.pollTimer = setTimeout(poll, 2000);
      } catch (error) {
        state.pollFailures = (state.pollFailures || 0) + 1;
        if (state.pollFailures > 4) {
          progressError({ error: "Связь с сервером потеряна. Проверьте, что сервер запущен, и обновите страницу." });
          return;
        }
        state.pollTimer = setTimeout(poll, 2500);
      }
    };
    poll();
  }

  function setData(analysis, options) {
    stopPolling();
    state.data = analysis;
    state.metric = "gold";
    state.team = "all";
    state.mistakeTeam = "all";
    renderReport(analysis);
    if (options && options.hash) history.replaceState(null, "", options.hash);
    loadHistory();
  }

  async function loadDemo(updateHash) {
    showLoading();
    try {
      const response = await fetch("/api/demo");
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Не удалось загрузить демо");
      setData(payload.analysis, { hash: updateHash === false ? null : "#demo" });
    } catch (error) {
      showError(error.message);
    }
  }

  async function loadMatch(id) {
    if (!/^\d{6,12}$/.test(id)) {
      showError("ID матча должен состоять из 6–12 цифр.");
      return;
    }
    showLoading();
    try {
      const response = await fetch(`/api/analyze?id=${encodeURIComponent(id)}`);
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        if (payload.code === "unparsed") {
          await startReplay(id);
          return;
        }
        throw new Error(payload.error || "Не удалось разобрать матч");
      }
      setData(payload.analysis, { hash: `#match=${id}` });
    } catch (error) {
      showError(error.message);
    }
  }

  async function loadFile(file) {
    if (!file) return;
    if (!/\.json$/i.test(file.name)) {
      showError("Нужен JSON матча. Файл .dem загружать не нужно — вставьте ID матча, и сервер сам скачает и распарсит реплей.");
      return;
    }
    showLoading();
    try {
      const text = await file.text();
      const response = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: text });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Не удалось разобрать файл");
      setData(payload.analysis, { hash: `#match=${payload.analysis.match.id}` });
      toast("Файл разобран");
    } catch (error) {
      showError(error.message);
    } finally {
      $("#file-input").value = "";
    }
  }

  async function loadHistory() {
    try {
      const response = await fetch("/api/history");
      const payload = await response.json();
      const items = (payload.items || []).slice(0, 4);
      const block = $("#history-block");
      if (!items.length) {
        block.hidden = true;
        return;
      }
      $("#history-list").innerHTML = items
        .map(
          (item) => `<a class="history-card" href="#match=${item.id}">
            <div class="hc-top"><span>${esc(item.date || "")}</span><span>${esc(item.duration || "")}</span></div>
            <div class="hc-score">${esc(String(item.score))}</div>
            <div class="hc-top"><span>${esc(item.winner === "radiant" ? "Radiant" : "Dire")} побеждает</span><span>#${item.id}</span></div>
            <div class="hc-heroes">${(item.heroes || []).slice(0, 10).map((h) => (typeof h === "string" ? `<span class="dim" style="font-size:9px">${esc(h)}</span>` : `<img src="${esc(h.img)}" alt="${esc(h.name)}" title="${esc(h.name)}" loading="lazy" onerror="this.remove()">`)).join("")}</div>
          </a>`
        )
        .join("");
      block.hidden = false;
    } catch {
      /* history is optional */
    }
  }

  /* ------------------------------------------------------------ chrome */
  let toastTimer;
  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (node.hidden = true), 2600);
  }

  function syncInput(id) {
    const input = $("#match-input");
    if (input && id) input.value = id;
  }

  function route() {
    const hash = location.hash || "";
    const match = hash.match(/#match=(\d{6,12})/);
    if (match) {
      syncInput(match[1]);
      loadMatch(match[1]);
      return;
    }
    if (hash === "#demo") {
      loadDemo(false);
      return;
    }
    if (state.data && document.getElementById(hash.slice(1))) {
      document.getElementById(hash.slice(1)).scrollIntoView({ behavior: "smooth" });
      return;
    }
    showLanding();
  }

  function bindChrome() {
    $("#search-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const value = $("#match-input").value.trim().replace(/\s+/g, "");
      if (!/^\d{6,12}$/.test(value)) {
        toast("Введите ID матча: только цифры, 6–12 знаков");
        return;
      }
      if (location.hash === `#match=${value}`) loadMatch(value);
      else location.hash = `#match=${value}`;
    });
    $("#demo-btn").addEventListener("click", () => {
      if (location.hash === "#demo") loadDemo();
      else location.hash = "#demo";
    });
    $("#hero-demo").addEventListener("click", () => {
      if (location.hash === "#demo") loadDemo();
      else location.hash = "#demo";
    });
    $("#upload-btn").addEventListener("click", () => $("#file-input").click());
    $("#file-input").addEventListener("change", (event) => loadFile(event.target.files[0]));
    $("#brand-link").addEventListener("click", (event) => {
      event.preventDefault();
      history.replaceState(null, "", location.pathname);
      showLanding();
    });
    $("#error-demo").addEventListener("click", () => {
      location.hash = "#demo";
      if (location.hash === "#demo") loadDemo();
    });
    $("#error-back").addEventListener("click", () => {
      history.replaceState(null, "", location.pathname);
      showLanding();
    });
    $("#progress-back").addEventListener("click", () => {
      stopPolling();
      history.replaceState(null, "", location.pathname);
      showLanding();
    });
    $("#progress-retry").addEventListener("click", () => {
      if (state.replayId) startReplay(state.replayId);
    });
    window.addEventListener("hashchange", route);
    document.addEventListener("keydown", (event) => {
      if (event.key === "/" && document.activeElement !== $("#match-input")) {
        event.preventDefault();
        $("#match-input").focus();
      }
    });
  }

  bindChrome();
  loadHistory();
  route();
})();
