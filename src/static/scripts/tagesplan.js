// Tagesplan auf der Startseite: Jetzt / Als Nächstes, farbiger Balken und Tagesansicht.
// Der Plan kommt vom Server (gleiche Berechnung wie fürs Display); Bearbeiten läuft über
// die Dialoge aus ansichten.js (window.Zeitplan).
(function () {
  "use strict";

  const Z = window.Zeitplan;
  const root = document.getElementById("tpRoot");
  if (!Z || !root) return;

  const DATA = JSON.parse(document.getElementById("zData").textContent);
  const PLUGINS = Object.fromEntries(DATA.plugins.map((p) => [p.id, p]));
  const PALETTE = ["#2f86d6", "#e0483f", "#0d977c", "#e07b22", "#8a55d4", "#2e9a54", "#c44d86", "#5d686a", "#c99000", "#357d9c"];
  const PPM = 1.2; // Pixel pro Minute
  const DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

  let plan = null;
  let shownDate = null; // null = heute
  let scrollToNow = true;
  let suppressClick = false; // nach dem Ziehen keinen Klick auswerten

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pad = (n) => String(n).padStart(2, "0");
  const hm = (m) => (m >= 1440 ? "24:00" : pad(Math.floor(m / 60)) + ":" + pad(m % 60));
  const tm = (s) => { const [h, m] = s.split(":").map(Number); return h * 60 + m; };
  const endMin = (f) => { const a = tm(f.start), b = tm(f.end); return b === 0 && a > 0 ? 1440 : b; };
  const parseKey = (k) => { const [y, m, d] = k.split("-").map(Number); return new Date(y, m - 1, d); };
  const dkey = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const clone = (o) => JSON.parse(JSON.stringify(o));

  function daysSummary(days) {
    const s = [...days].sort((a, b) => a - b);
    if (s.length === 7) return "täglich";
    if (s.join() === "0,1,2,3,4") return "Mo–Fr";
    if (s.join() === "5,6") return "Sa, So";
    return s.map((d) => DAYS[d]).join(", ");
  }
  const views = () => Z.schedule().views;
  const viewById = (id) => views().find((v) => v.id === id);
  const fixedById = (view, id) => view && view.fixed_times.find((f) => f.id === id);
  function colorOf(viewId) {
    const i = views().findIndex((v) => v.id === viewId);
    return PALETTE[(i < 0 ? 0 : i) % PALETTE.length];
  }

  // ---------- Laden ----------
  async function load() {
    try {
      const url = DATA.urls.day + (shownDate ? "?datum=" + shownDate : "");
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return;
      plan = await response.json();
      render();
    } catch (e) { console.error("Tagesplan konnte nicht geladen werden", e); }
  }

  // ---------- Darstellung ----------
  function render() {
    if (!plan) return;
    renderTimezone();
    renderNow();
    renderDayHead();
    renderBar();
    renderDay();
  }

  // Rechnet das Gerät mit einer anderen Zeitzone als das Handy, stimmen alle Uhrzeiten nicht.
  const phoneTimezone = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { return ""; } })();
  function renderTimezone() {
    let box = document.getElementById("tpTz");
    if (!box) { box = document.createElement("div"); box.id = "tpTz"; root.prepend(box); }
    const phoneOffset = -new Date().getTimezoneOffset();
    if (plan.utc_offset_minutes === undefined || plan.utc_offset_minutes === phoneOffset) { box.innerHTML = ""; return; }
    const now = new Date();
    const phoneTime = pad(now.getHours()) + ":" + pad(now.getMinutes());
    const button = phoneTimezone
      ? '<button type="button" class="z-btn z-primary" data-tp="set-tz">„' + esc(phoneTimezone) + '“ übernehmen</button>'
      : '<a class="z-btn" href="/settings">Zu den Einstellungen</a>';
    box.innerHTML = '<div class="z-banner tp-tz"><span class="z-grow"><strong>Die Uhrzeit von InkyPi stimmt nicht mit deinem Handy überein.</strong> ' +
      "InkyPi rechnet mit der Zeitzone „" + esc(plan.timezone) + "“ (" + esc(plan.device_time) + " Uhr), dein Handy " +
      (phoneTimezone ? "mit „" + esc(phoneTimezone) + "“ " : "") + "(" + phoneTime + " Uhr). Davon hängen der Zeitplan und alle Uhrzeiten auf dem Display ab.</span>" + button + "</div>";
  }

  async function setTimezone() {
    try {
      const response = await fetch(DATA.urls.timezone, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ timezone: phoneTimezone }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      Z.toast(result.message);
      scrollToNow = true;
      load();
    } catch (e) { showResponseModal("failure", e.message); }
  }

  function renderNow() {
    const box = document.getElementById("tpNow");
    if (!plan.today || !plan.now) { box.hidden = true; return; }
    box.hidden = false;
    const n = plan.now;
    const left = n.minutes_left >= 60 ? Math.floor(n.minutes_left / 60) + " Std" + (n.minutes_left % 60 ? " " + (n.minutes_left % 60) + " Min" : "") : n.minutes_left + " Min";
    const kinds = { rotation: "Rotation", fixed: "Feste Zeit", quiet: "Ruhezeit", override: "Manuell", idle: "Nichts geplant" };
    let title, meta;
    if (n.view_name) { title = n.view_name; meta = kinds[n.kind] + " bis " + n.end + " · noch " + left; }
    else if (n.kind === "quiet") { title = "Ruhezeit"; meta = "Das Display wird bis " + n.end + " nicht aktualisiert"; }
    else { title = "Keine Ansicht geplant"; meta = "Das letzte Bild bleibt bis " + n.end + " stehen"; }
    let data = "";
    if (n.view_name) {
      data = n.data_from ? "Daten von " + n.data_from : "Daten werden geholt";
      if (n.next_refresh) data += " · nächste Aktualisierung " + n.next_refresh;
    }
    const icon = n.plugin_id && PLUGINS[n.plugin_id] ? '<img class="z-icon" alt="" src="' + esc(PLUGINS[n.plugin_id].icon) + '">' : "";
    const action = n.kind === "override"
      ? '<button type="button" class="z-btn" data-tp="end-override">Beenden</button>'
      : '<span class="tp-kind tp-' + n.kind + '">' + kinds[n.kind] + "</span>";
    let next = "–";
    if (plan.next) {
      const at = (plan.next.tomorrow ? "morgen " : "") + plan.next.start;
      next = plan.next.view_name ? esc(plan.next.view_name) + " um " + at : plan.next.kind === "quiet" ? "Ruhezeit ab " + at : "Nichts geplant ab " + at;
    }
    box.innerHTML =
      '<div class="z-row">' + icon + '<span class="z-grow"><span class="z-title">' + esc(title) + '</span><span class="z-meta">' + esc(meta) + "</span>" +
      (data ? '<span class="z-meta">' + esc(data) + "</span>" : "") + "</span>" + action + "</div>" +
      (plan.next ? '<div class="z-row"><span class="z-grow"><span class="z-meta">Als Nächstes</span><span class="z-title" style="font-weight:400">' + next + "</span></span></div>" : "");
  }

  function renderDayHead() {
    const d = parseKey(plan.date);
    const today = new Date();
    const diff = Math.round((d - parseKey(dkey(today))) / 86400000);
    const label = diff === 0 ? "Heute" : diff === 1 ? "Morgen" : diff === -1 ? "Gestern"
      : d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });
    document.getElementById("tpDay").textContent = label + (Math.abs(diff) <= 1 ? ", " + d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" }) : "");
    document.querySelector('[data-tp="today"]').hidden = diff === 0;
  }

  function renderBar() {
    const segs = plan.segments.filter((s) => s.kind !== "idle");
    let h = segs.map((s) => {
      const style = "left:" + (s.start / 14.4) + "%;width:" + ((s.end - s.start) / 14.4) + "%" + (s.view_id ? ";background:" + colorOf(s.view_id) : "");
      const title = hm(s.start) + "–" + hm(s.end) + " " + (s.view_name || (s.kind === "quiet" ? "Ruhezeit" : ""));
      return '<div class="tp-b-' + s.kind + '" style="' + style + '" title="' + esc(title) + '"></div>';
    }).join("");
    if (plan.today) h += '<div class="tp-nowline" style="left:' + (plan.now_minute / 14.4) + '%"></div>';
    document.getElementById("tpBar").innerHTML = h;

    const seen = [];
    plan.segments.forEach((s) => { if (s.view_id && !seen.some((x) => x.id === s.view_id)) seen.push({ id: s.view_id, name: s.view_name }); });
    document.getElementById("tpLegend").innerHTML =
      seen.map((v) => '<span><i style="background:' + colorOf(v.id) + '"></i>' + esc(v.name) + "</span>").join("") +
      (plan.segments.some((s) => s.kind === "quiet") ? '<span><i class="tp-q"></i>Ruhezeit</span>' : "") +
      (seen.length ? '<span style="width:100%">Kräftig: feste Zeit · blass: Rotation</span>' : '<span>Für diesen Tag ist nichts geplant.</span>');
  }

  function renderDay() {
    const inner = document.getElementById("tpInner");
    inner.style.height = 1440 * PPM + "px";
    let h = "";
    for (let i = 0; i <= 24; i++) h += '<div class="tp-hour" style="top:' + i * 60 * PPM + 'px"><span>' + pad(i) + ":00</span></div>";
    plan.segments.forEach((s, idx) => {
      if (s.kind === "idle") return;
      const top = s.start * PPM, height = Math.max(3, (s.end - s.start) * PPM - 2);
      const color = s.view_id ? colorOf(s.view_id) : "";
      const pos = 'style="top:' + top + "px;height:" + height + "px" + (color ? ";--c:" + color : "") + '"';
      if (s.kind === "rotation") {
        h += '<div class="tp-block tp-rotation" data-seg="' + idx + '" ' + pos + ">" + (height >= 15 ? '<span class="tp-label"><i></i>' + esc(s.view_name) + "</span>" : "") + "</div>";
      } else if (s.kind === "fixed") {
        const view = viewById(s.view_id), fixed = fixedById(view, s.fixed_id);
        const movable = fixed && tm(fixed.start) < endMin(fixed) && s.start === tm(fixed.start);
        const when = fixed ? (fixed.date ? "einmalig" : daysSummary(fixed.days)) : "";
        let ticks = "";
        if (s.refresh_minutes) for (let t = s.start + s.refresh_minutes; t < s.end; t += s.refresh_minutes) ticks += '<span class="tp-tick" style="top:' + (t - s.start) * PPM + 'px"></span>';
        h += '<div class="tp-block tp-fixed" data-seg="' + idx + '" ' + pos + ">" +
          "<b>" + esc(s.view_name) + '</b><div class="tp-sub">' + hm(s.start) + "–" + hm(s.end) + " · " + esc(when) + "</div>" +
          (height > 56 && s.refresh_minutes ? '<div class="tp-sub">Daten alle ' + s.refresh_minutes + " Min</div>" : "") + ticks +
          (movable ? '<span class="tp-move" data-move title="Ziehen zum Verschieben" aria-label="Verschieben">↕</span><span class="tp-grip" data-grip title="Ziehen, um die Dauer zu ändern"></span>' : "") + "</div>";
      } else if (s.kind === "quiet") {
        h += '<div class="tp-block tp-quiet" data-seg="' + idx + '" ' + pos + ">Ruhezeit</div>";
      } else if (s.kind === "override") {
        h += '<div class="tp-block tp-override" data-seg="' + idx + '" ' + pos + "><b>" + esc(s.view_name) + "</b> · manuell</div>";
      }
    });
    if (plan.today) h += '<div class="tp-now-line" style="top:' + plan.now_minute * PPM + 'px"></div>';
    inner.innerHTML = h;

    const dv = document.getElementById("tpDayview");
    if (scrollToNow) {
      const target = plan.today ? plan.now_minute - 60 : 6 * 60;
      dv.scrollTop = Math.max(0, target * PPM);
      scrollToNow = false;
    }
  }

  // ---------- Bedienung ----------
  function minuteAt(e) {
    const r = document.getElementById("tpInner").getBoundingClientRect();
    return Math.max(0, Math.min(1439, Math.floor((e.clientY - r.top) / PPM)));
  }
  const roundTo15 = (m) => Math.min(1380, Math.round(m / 15) * 15);

  function segmentActions(seg, minute) {
    const at = roundTo15(minute);
    const addFixed = { label: "Feste Zeit ab " + hm(at) + " hinzufügen …", run: () => Z.pickViewForFixed(at) };
    const range = hm(seg.start) + "–" + hm(seg.end);
    if (seg.kind === "rotation") {
      Z.actions(range + " · Rotation", [{ label: "„" + seg.view_name + "“ bearbeiten", run: () => Z.openView(seg.view_id) }, addFixed]);
    } else if (seg.kind === "quiet") {
      Z.actions(range + " · Ruhezeit", [{ label: "Ruhezeit bearbeiten", run: () => { location.href = DATA.urls.ansichten; } }, addFixed]);
    } else if (seg.kind === "override") {
      Z.actions("„" + seg.view_name + "“ wird manuell angezeigt", [{ label: "Manuelle Anzeige beenden", run: () => Z.endOverride() }, addFixed]);
    } else {
      Z.actions(range + " · nichts geplant", [addFixed]);
    }
  }

  root.addEventListener("click", (e) => {
    const el = e.target.closest("[data-tp]");
    if (el) {
      const action = el.dataset.tp;
      if (action === "prev" || action === "next") {
        const d = parseKey(plan.date);
        d.setDate(d.getDate() + (action === "prev" ? -1 : 1));
        shownDate = dkey(d); scrollToNow = true; load();
      } else if (action === "today") { shownDate = null; scrollToNow = true; load(); }
      else if (action === "add-fixed") {
        const now = new Date();
        Z.pickViewForFixed(Math.min(1380, (now.getHours() + 1) * 60));
      } else if (action === "end-override") Z.endOverride();
      else if (action === "set-tz") setTimezone();
      return;
    }
    const bar = e.target.closest("#tpBar");
    if (bar) {
      const r = bar.getBoundingClientRect();
      const m = ((e.clientX - r.left) / r.width) * 1440;
      document.getElementById("tpDayview").scrollTo({ top: Math.max(0, (m - 45) * PPM), behavior: "smooth" });
      return;
    }
    if (!e.target.closest("#tpInner")) return;
    const fixedBlock = e.target.closest(".tp-fixed");
    if (fixedBlock) {
      // Öffnen erst beim Klick, nicht schon bei pointerup: sonst landet der Klick des Fingers im neuen Dialog
      if (suppressClick) { suppressClick = false; return; }
      const seg = plan.segments[+fixedBlock.dataset.seg];
      const view = viewById(seg.view_id), fixed = fixedById(view, seg.fixed_id);
      if (fixed) Z.openFixed(view.id, fixed);
      return;
    }
    const m = minuteAt(e);
    const seg = plan.segments.find((s) => m >= s.start && m < s.end);
    if (seg) segmentActions(seg, m);
  });

  // Feste Zeiten: antippen öffnet sie, am ↕ ziehen verschiebt, am unteren Rand ziehen ändert die Dauer.
  // Mit der Maus kann der ganze Block gezogen werden; am Handy nur über die Griffe, damit Scrollen geht.
  root.addEventListener("pointerdown", (e) => {
    const block = e.target.closest(".tp-fixed");
    if (!block) return;
    const seg = plan.segments[+block.dataset.seg];
    const view = viewById(seg.view_id), fixed = fixedById(view, seg.fixed_id);
    if (!fixed) return;
    const onHandle = e.target.closest("[data-move],[data-grip]");
    const movable = !!block.querySelector("[data-move]");
    const canDrag = movable && (onHandle || e.pointerType === "mouse");
    const resize = !!e.target.closest("[data-grip]");
    if (canDrag) { e.preventDefault(); block.setPointerCapture(e.pointerId); }

    const a0 = tm(fixed.start), b0 = endMin(fixed), y0 = e.clientY;
    let a = a0, b = b0, moved = false, scrolled = false;
    const world = clone(Z.schedule());
    const cand = fixedById(world.views.find((v) => v.id === view.id), fixed.id);
    const sub = block.querySelector(".tp-sub");

    const move = (ev) => {
      if (!canDrag) { if (Math.abs(ev.clientY - y0) > 6) scrolled = true; return; }
      if (!moved && Math.abs(ev.clientY - y0) < 6) return;
      moved = true;
      block.classList.add("tp-dragging");
      const d = Math.round((ev.clientY - y0) / PPM / 5) * 5;
      if (resize) { a = a0; b = Math.max(a0 + 10, Math.min(1440, b0 + d)); }
      else { const len = b0 - a0; a = Math.max(0, Math.min(1440 - len, a0 + d)); b = a + len; }
      block.style.top = a * PPM + "px";
      block.style.height = (b - a) * PPM - 2 + "px";
      cand.start = hm(a % 1440); cand.end = hm(b % 1440);
      if (sub) sub.textContent = hm(a) + "–" + hm(b) + " · " + (fixed.date ? "einmalig" : daysSummary(fixed.days));
      block.classList.toggle("tp-bad", !!Z.findConflict(cand, world));
    };
    const up = async (ev) => {
      block.removeEventListener("pointermove", move);
      block.removeEventListener("pointerup", up);
      block.removeEventListener("pointercancel", up);
      // Abgebrochen (z. B. weil gescrollt wurde): nichts öffnen
      if (ev.type === "pointercancel" || scrolled) { if (moved) render(); return; }
      if (!moved) return;  // Antippen: öffnet der Klick-Handler
      suppressClick = true;
      setTimeout(() => { suppressClick = false; }, 500);
      if (a === a0 && b === b0) { render(); return; }
      if (Z.findConflict(cand, world)) {
        render();
        Z.openFixed(view.id, cand, null, true);  // Überschneidung: gleich mit Lösungsvorschlägen
        return;
      }
      try {
        const days = fixed.date ? "" : daysSummary(fixed.days);
        const scope = fixed.date ? "" : " · gilt für " + (days === "täglich" ? "jeden Tag" : days);
        await Z.save(world, (resize ? "Dauer geändert" : "Verschoben") + scope);
      } catch (err) { render(); showResponseModal("failure", err.message); }
    };
    block.addEventListener("pointermove", move);
    block.addEventListener("pointerup", up);
    block.addEventListener("pointercancel", up);
  });

  Z.onChange(() => load());
  setInterval(() => { if (!shownDate && !document.querySelector(".z-scrim")) load(); }, 60 * 1000);
  load();
})();
