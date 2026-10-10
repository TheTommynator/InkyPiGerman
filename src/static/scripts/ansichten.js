// Seite „Ansichten“: Liste, Bearbeiten, feste Zeiten mit Konfliktlösung, Ruhezeit.
// Gesichert wird immer der ganze Zeitplan (PUT /api/zeitplan); der Server prüft alles noch einmal.
(function () {
  "use strict";

  const DATA = JSON.parse(document.getElementById("zData").textContent);
  const URLS = DATA.urls;
  const PLUGINS = Object.fromEntries(DATA.plugins.map((p) => [p.id, p]));
  const DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
  const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];
  const DURATIONS = [5, 10, 15, 20, 30, 60];
  const INTERVALS = [5, 15, 30, 60];

  let schedule = DATA.schedule;
  let sheet = null;
  let busy = false;

  // ---------- Hilfsfunktionen ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const tm = (s) => { const [h, m] = s.split(":").map(Number); return h * 60 + m; };
  const pad = (n) => String(n).padStart(2, "0");
  const hm = (m) => (m >= 1440 ? "24:00" : pad(Math.floor(m / 60)) + ":" + pad(m % 60));
  const hmS = (m) => hm(m % 1440);
  const endMin = (f) => { const a = tm(f.start), b = tm(f.end); return b === 0 && a > 0 ? 1440 : b; };
  const parseKey = (k) => { const [y, m, d] = k.split("-").map(Number); return new Date(y, m - 1, d); };
  const dkey = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const wdOf = (d) => (d.getDay() + 6) % 7;
  const uid = (p) => p + Math.random().toString(36).slice(2, 10);
  const shortDate = (k) => parseKey(k).toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  const durLabel = (m) => (m % 60 === 0 ? m / 60 + " Std" : m > 60 ? Math.floor(m / 60) + " Std " + (m % 60) + " Min" : m + " Min");
  const plugin = (id) => PLUGINS[id] || { name: id, icon: "", auto_refresh_minutes: 60 };

  function daysSummary(days) {
    const s = [...days].sort((a, b) => a - b);
    if (s.length === 7) return "Täglich";
    if (!s.length) return "keine Tage";
    if (s.join() === "0,1,2,3,4") return "Mo–Fr";
    if (s.join() === "5,6") return "Sa, So";
    if (s.length > 2 && s.every((d, i) => i === 0 || d === s[i - 1] + 1)) return DAYS[s[0]] + "–" + DAYS[s[s.length - 1]];
    return s.map((d) => DAYS[d]).join(", ");
  }
  const whenText = (f) => (f.date ? shortDate(f.date) : daysSummary(f.days));
  const rangeText = (f) => f.start + "–" + hm(endMin(f));
  const fixedSummary = (f) => whenText(f) + " · " + rangeText(f);
  const refreshText = (n) => (n === 0 ? "nur beim Einblenden" : n === 60 ? "jede Stunde" : "alle " + n + " Min");

  function refreshDescription(view) {
    const r = view.refresh || { mode: "auto" };
    if (r.mode === "interval") return refreshText(r.minutes);
    if (r.mode === "on_show") return refreshText(0);
    if (r.mode === "daily") return "täglich um " + r.time;
    return refreshText(plugin(view.plugin_id).auto_refresh_minutes);
  }

  function viewSummary(v) {
    const parts = [];
    if (v.rotation) {
      let r = durLabel(v.duration_minutes);
      if (v.limit) {
        const w = v.limit.windows.map((x) => x.start + "–" + hm(tm(x.end) || 1440)).join(", ");
        const d = v.limit.days.length < 7 ? daysSummary(v.limit.days) : "";
        r += " · nur " + [d, w].filter(Boolean).join(" ");
      }
      parts.push(r);
    }
    if (v.fixed_times.length) {
      const f = v.fixed_times.slice(0, 2).map((x) => whenText(x) + " " + x.start);
      parts.push(f.join(", ") + (v.fixed_times.length > 2 ? " +" + (v.fixed_times.length - 2) : ""));
    }
    return parts.join(" · ") || "Nur über „Jetzt anzeigen“";
  }

  function toast(msg) {
    const root = document.getElementById("zToastRoot");
    root.innerHTML = '<div class="z-toast" role="status">' + esc(msg) + "</div>";
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { root.innerHTML = ""; }, 3000);
  }

  async function api(method, url, body) {
    const options = { method, headers: {} };
    if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    const response = await fetch(url, options);
    let result = {};
    try { result = await response.json(); } catch (e) { /* leer */ }
    if (!response.ok) throw new Error(result.error || "Unbekannter Fehler (" + response.status + ")");
    return result;
  }

  function payload(world) {
    return {
      views: world.views.map((v) => ({
        id: v.id, name: v.name, rotation: v.rotation, duration_minutes: v.duration_minutes,
        refresh: v.refresh, limit: v.limit, fixed_times: v.fixed_times,
      })),
      quiet: world.quiet,
      default_duration_minutes: world.default_duration_minutes,
    };
  }

  async function saveWorld(world) {
    const result = await api("PUT", URLS.schedule, payload(world));
    schedule = result.schedule;
    return result;
  }

  // ---------- Überschneidungen (gleiche Regeln wie im Server) ----------
  function pieces(f) {
    const a = tm(f.start), b = endMin(f);
    if (a === b) return [];
    const base = a < b ? [[a, b, 0]] : [[a, 1440, 0], [0, b, 1]];
    const out = [];
    for (const [s, e, shift] of base) {
      if (f.date) { const d = addDays(parseKey(f.date), shift); out.push({ wd: wdOf(d), date: dkey(d), a: s, b: e, shift }); }
      else for (const d of f.days) out.push({ wd: (d + shift) % 7, date: null, a: s, b: e, shift });
    }
    return out;
  }
  function overlaps(f1, f2) {
    for (const p of pieces(f1)) for (const q of pieces(f2)) {
      if (!(p.a < q.b && q.a < p.b)) continue;
      if (p.date && q.date) { if (p.date === q.date) return true; continue; }
      if (p.wd !== q.wd) continue;
      if (p.date && (f2.except_dates || []).includes(dkey(addDays(parseKey(p.date), -q.shift)))) continue;
      if (q.date && (f1.except_dates || []).includes(dkey(addDays(parseKey(q.date), -p.shift)))) continue;
      return true;
    }
    return false;
  }
  function findConflict(f, world) {
    for (const v of world.views) for (const o of v.fixed_times) if (o.id !== f.id && overlaps(f, o)) return { v, f: o };
    return null;
  }

  // Vorschläge, wie sich ein Konflikt direkt lösen lässt
  function resolutions(c, world) {
    const conf = findConflict(asFixed(c), world);
    if (!conf) return null;
    const o = conf.f, V = conf.v, name = "„" + V.name + "“";
    const opts = [];
    const ca = tm(c.start), cb = endMin(c), oa = tm(o.start), ob = endMin(o);
    const scope = !o.date ? daysSummary(o.days) : "";
    const otherDays = !o.date && o.days.length > 1 ? " (gilt für " + (scope === "Täglich" ? "jeden Tag" : scope) + ")" : "";
    if (ca < cb && oa < ob) {
      const len = cb - ca;
      for (const na of [ob, oa - len]) {
        if (na < 0 || na + len > 1440) continue;
        const t = Object.assign({}, c, { start: hmS(na), end: hmS(na + len) });
        if (!findConflict(asFixed(t), world)) { opts.push({ label: "Meine Zeit verschieben auf " + hm(na) + "–" + hm(na + len), run: () => { c.start = t.start; c.end = t.end; } }); break; }
      }
      if (ca < oa && cb > oa) opts.push({ label: "Meine Zeit kürzen auf " + hm(ca) + "–" + hm(oa), run: () => { c.end = hmS(oa); } });
      else if (cb > ob && ca < ob) opts.push({ label: "Meine Zeit kürzen auf " + hm(ob) + "–" + hm(cb), run: () => { c.start = hmS(ob); } });
      if (oa < ca) opts.push({ label: name + " kürzen auf " + hm(oa) + "–" + hm(ca) + otherDays, other: V, run: () => { o.end = hmS(ca); } });
      else if (ob > cb) opts.push({ label: name + " später beginnen: " + hm(cb) + "–" + hm(ob) + otherDays, other: V, run: () => { o.start = hmS(cb); } });
    }
    const drop = () => { V.fixed_times = V.fixed_times.filter((x) => x !== o); };
    if (o.date) {
      opts.push({ label: name + " am " + shortDate(o.date) + " ersetzen", other: V, run: drop });
    } else if (c.mode === "date") {
      const hit = [c.date, dkey(addDays(parseKey(c.date), -1))].filter((k) => overlaps(asFixed(c), { start: o.start, end: o.end, date: k }));
      opts.push({ label: name + " am " + shortDate(c.date) + " aussetzen", other: V, run: () => { o.except_dates = (o.except_dates || []).concat(hit); } });
    } else {
      const hitDays = o.days.filter((d) => overlaps(asFixed(c), Object.assign({}, o, { days: [d] })));
      const all = hitDays.length === o.days.length;
      opts.push({ label: all ? name + " ersetzen (" + fixedSummary(o) + " entfällt)" : name + " am " + daysSummary(hitDays) + " ersetzen", other: V,
        run: () => { o.days = o.days.filter((d) => !hitDays.includes(d)); if (!o.days.length) drop(); } });
    }
    return { conf, opts };
  }

  // Entwurf einer festen Zeit (mit mode) <-> gespeichertes Format
  function asFixed(d) {
    return d.mode === "date"
      ? { id: d.id, start: d.start, end: d.end, date: d.date }
      : { id: d.id, start: d.start, end: d.end, days: d.days.slice().sort(), except_dates: d.except_dates || [] };
  }
  function toDraft(f) {
    return { id: f.id, start: f.start, end: f.end, mode: f.date ? "date" : "weekly", days: f.days ? f.days.slice() : [], date: f.date || dkey(new Date()), except_dates: (f.except_dates || []).slice() };
  }

  // ---------- Hauptseite ----------
  const sw = (field, on, label) => '<label class="z-switch"><input type="checkbox" role="switch" data-f="' + field + '"' + (on ? " checked" : "") + ' aria-label="' + esc(label) + '"><span></span></label>';
  const segDur = (action, value) => {
    const values = DURATIONS.includes(value) ? DURATIONS : DURATIONS.concat([value]).sort((a, b) => a - b);
    return '<div class="z-seg" role="group" aria-label="Anzeigedauer">' + values.map((d) => '<button type="button" data-a="' + action + '" data-v="' + d + '" aria-pressed="' + (d === value) + '">' + durLabel(d) + "</button>").join("") + "</div>";
  };
  const dayChips = (action, days) => '<div class="z-days">' + DAYS.map((n, i) => '<button type="button" class="z-day" data-a="' + action + '" data-v="' + i + '" aria-pressed="' + days.includes(i) + '">' + n + "</button>").join("") + "</div>";

  function thumb(v) {
    const icon = plugin(v.plugin_id).icon;
    return '<img class="z-thumb" alt="" src="' + URLS.view + encodeURIComponent(v.id) + "/bild?t=" + encodeURIComponent(v.latest_refresh_time || "") + '" data-fallback="' + esc(icon) + '">';
  }

  function viewRow(v, draggable) {
    return '<div class="z-row"' + (draggable ? ' data-drag="' + esc(v.id) + '"' : "") + ">" +
      (draggable ? '<span class="z-handle" data-handle title="Zum Sortieren ziehen" aria-hidden="true">≡</span>' : "") +
      '<button type="button" class="z-row" style="padding:0;min-height:0;background:none" data-a="open-view" data-v="' + esc(v.id) + '">' + thumb(v) +
      '<span class="z-grow"><span class="z-title">' + esc(v.name) + '</span><span class="z-meta">' + esc(viewSummary(v)) + "</span></span>" +
      '<span class="z-chev">›</span></button></div>';
  }

  const listeners = [];
  function notify() { listeners.forEach((cb) => { try { cb(schedule); } catch (e) { console.error(e); } }); }

  function render() {
    if (!DATA.active) return;
    notify();
    if (!document.getElementById("zLists")) return;
    const rot = schedule.views.filter((v) => v.rotation);
    const fix = schedule.views.filter((v) => !v.rotation && v.fixed_times.length);
    const none = schedule.views.filter((v) => !v.rotation && !v.fixed_times.length);
    document.getElementById("zLead").textContent = schedule.views.length + " Ansichten · " + rot.length + " in der Rotation";

    const o = schedule.override;
    const ov = o && schedule.views.find((v) => v.id === o.view_id);
    document.getElementById("zBanner").innerHTML = ov
      ? '<div class="z-banner"><span class="z-grow">„' + esc(ov.name) + "“ wird manuell angezeigt " +
        (o.until ? "bis " + new Date(o.until).toLocaleString("de-DE", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "bis du es beendest") +
        '.</span><button type="button" class="z-btn" data-a="override-end">Beenden</button></div>'
      : "";

    let h = "";
    if (rot.length) h += '<div class="z-ghead">In der Rotation</div><div class="z-group" id="zRotList">' + rot.map((v) => viewRow(v, rot.length > 1)).join("") +
      '</div><div class="z-gfoot">Zum Sortieren am Griff ziehen. Die Rotation beginnt jeden Tag um 00:00 mit der ersten Ansicht, so liegen die Wechsel fest auf der Uhr.</div>';
    if (fix.length) h += '<div class="z-ghead">Nur zu festen Zeiten</div><div class="z-group">' + fix.map((v) => viewRow(v, false)).join("") + "</div>";
    if (none.length) h += '<div class="z-ghead">Nicht eingeplant</div><div class="z-group">' + none.map((v) => viewRow(v, false)).join("") +
      '</div><div class="z-gfoot">Diese Ansichten erscheinen nur, wenn du sie über „Jetzt anzeigen“ aufrufst.</div>';
    if (!schedule.views.length) h += '<div class="z-group" style="margin-top:16px"><button type="button" class="z-row z-link" data-a="add-view">Erste Ansicht hinzufügen</button></div>';
    document.getElementById("zLists").innerHTML = h;

    const q = schedule.quiet;
    document.getElementById("zSettings").innerHTML =
      '<div class="z-ghead">Ruhezeit</div><div class="z-group">' +
      '<div class="z-row"><span class="z-grow">Ruhezeit</span>' + sw("quiet.enabled", q.enabled, "Ruhezeit") + "</div>" +
      (q.enabled ? '<div class="z-row"><span class="z-grow">Zeitraum</span><span class="z-timepair"><input type="time" data-f="quiet.start" value="' + esc(q.start) + '" aria-label="Ruhezeit von">–<input type="time" data-f="quiet.end" value="' + esc(q.end) + '" aria-label="Ruhezeit bis"></span></div>' : "") +
      '</div><div class="z-gfoot">In der Ruhezeit wird das Display nicht aktualisiert, das letzte Bild bleibt stehen. Feste Zeiten haben Vorrang.</div>' +
      '<div class="z-ghead">Neue Ansichten</div><div class="z-group"><div class="z-row z-stack"><span>Standard-Anzeigedauer</span>' + segDur("default-dur", schedule.default_duration_minutes) + "</div></div>" +
      '<div class="z-ghead">So entscheidet das Display</div><div class="z-group z-rules">' +
      rule(1, "Jetzt anzeigen", "Gilt, bis die gewählte Zeit vorbei ist.") +
      rule(2, "Feste Zeit", "Steht eine feste Zeit an, bleibt diese Ansicht auf dem Display.") +
      rule(3, "Ruhezeit", "Sonst wird in der Ruhezeit nichts aktualisiert.") +
      rule(4, "Rotation", "Sonst wechseln sich die Ansichten ab, jede mit ihrer eigenen Anzeigedauer.") +
      '</div><div class="z-gfoot">Unabhängig davon holt jede Ansicht, solange sie zu sehen ist, in ihrem eigenen Abstand neue Daten.</div>';
  }
  const rule = (n, t, d) => '<div class="z-row"><span class="z-num">' + n + '</span><span class="z-grow"><span class="z-title">' + t + '</span><span class="z-meta z-wrap">' + d + "</span></span></div>";

  // ---------- Sheets ----------
  const head = (left, title, right) => '<div class="z-sheet-head">' +
    (left ? '<button type="button" class="z-left" data-a="' + left[0] + '">' + left[1] + "</button>" : "<span></span>") +
    "<h2>" + esc(title) + "</h2>" +
    (right ? '<button type="button" class="z-right" data-a="' + right[0] + '"' + (busy ? " disabled" : "") + ">" + right[1] + "</button>" : "<span></span>") + "</div>";

  function renderSheet(keepScroll) {
    const root = document.getElementById("zSheetRoot");
    const old = root.querySelector(".z-sheet");
    const top = keepScroll && old ? old.scrollTop : 0;
    if (!sheet) { root.innerHTML = ""; document.body.style.overflow = ""; return; }
    const body = { gallery: galleryHtml, view: viewHtml, fixed: fixedHtml, show: showHtml, pickview: pickViewHtml, actions: actionsHtml }[sheet.mode]();
    root.innerHTML = '<div class="z-scrim" data-a="scrim"><div class="z-sheet" role="dialog" aria-modal="true">' + body + "</div></div>";
    document.body.style.overflow = "hidden";
    const s = root.querySelector(".z-sheet");
    if (keepScroll) { s.style.animation = "none"; s.scrollTop = top; }
  }

  function galleryHtml() {
    return head(["close", "Abbrechen"], "Ansicht hinzufügen") +
      '<p class="z-gfoot" style="margin:0 4px 12px">Wähle ein Plugin. Auf der nächsten Seite richtest du es ein und fügst es als Ansicht hinzu.</p>' +
      '<div class="z-gallery">' + DATA.plugins.map((p) => '<a class="z-gitem" href="' + URLS.plugin + encodeURIComponent(p.id) + '"><img class="z-icon" alt="" src="' + esc(p.icon) + '"><span>' + esc(p.name) + "</span></a>").join("") + "</div>";
  }

  function touchedNote() {
    const names = [...sheet.touched];
    return names.length ? '<div class="z-notice z-info">Beim Sichern wird auch ' + names.map((n) => "„" + esc(n) + "“").join(", ") + " angepasst.</div>" : "";
  }

  function refreshSelect(v) {
    const r = v.refresh || { mode: "auto" };
    const current = r.mode === "interval" ? "i" + r.minutes : r.mode;
    const intervals = INTERVALS.includes(r.minutes) || r.mode !== "interval" ? INTERVALS : INTERVALS.concat([r.minutes]).sort((a, b) => a - b);
    const opt = (val, label) => '<option value="' + val + '"' + (val === current ? " selected" : "") + ">" + label + "</option>";
    return '<select data-f="refresh" aria-label="Daten aktualisieren">' +
      opt("auto", "Automatisch") + opt("on_show", "Nur beim Einblenden") +
      intervals.map((n) => opt("i" + n, n === 60 ? "Jede Stunde" : "Alle " + n + " Min")).join("") +
      opt("daily", "Täglich um …") + "</select>";
  }
  function refreshFoot(v) {
    const r = v.refresh || { mode: "auto" };
    const pre = r.mode === "auto" ? "Automatisch heißt bei " + plugin(v.plugin_id).name + ": " + refreshDescription(v) + ". " : "";
    if (r.mode === "daily") return "Die Daten werden einmal am Tag ab der gewählten Uhrzeit neu geholt.";
    const n = r.mode === "interval" ? r.minutes : r.mode === "on_show" ? 0 : plugin(v.plugin_id).auto_refresh_minutes;
    return pre + (n === 0
      ? "Die Daten werden geholt, wenn die Ansicht erscheint, und bleiben dann stehen."
      : "Solange die Ansicht zu sehen ist, holt sie " + refreshText(n) + " neue Daten. Das Display zeichnet nur neu, wenn sich das Bild ändert.");
  }

  function viewHtml() {
    const v = sheet.draft;
    let h = head(["close", "Abbrechen"], v.name, ["save-view", "Fertig"]);
    h += '<div class="z-hero"><img alt="" src="' + esc(plugin(v.plugin_id).icon) + '"><span>' + esc(plugin(v.plugin_id).name) + "</span></div>";
    if (sheet.error) h += '<div class="z-notice z-warn">' + esc(sheet.error) + "</div>";
    h += touchedNote();
    h += '<div class="z-group" style="margin-top:12px"><div class="z-row"><label for="zName">Name</label><input type="text" id="zName" data-f="name" value="' + esc(v.name) + '" maxlength="60"></div></div>';

    h += '<div class="z-ghead">Rotation</div><div class="z-group"><div class="z-row"><span class="z-grow">In der Rotation zeigen</span>' + sw("rotation", v.rotation, "In der Rotation zeigen") + "</div>";
    if (v.rotation) {
      h += '<div class="z-row z-stack"><span>Anzeigedauer</span>' + segDur("dur", v.duration_minutes) + "</div>";
      h += '<div class="z-row"><span class="z-grow">Nur zu bestimmten Zeiten</span>' + sw("limit", !!v.limit, "Nur zu bestimmten Zeiten") + "</div>";
      if (v.limit) {
        v.limit.windows.forEach((w, i) => {
          h += '<div class="z-row"><span class="z-grow">Zeitraum</span><span class="z-timepair"><input type="time" data-f="win.start" data-i="' + i + '" value="' + esc(w.start) + '" aria-label="Von">–<input type="time" data-f="win.end" data-i="' + i + '" value="' + esc(w.end) + '" aria-label="Bis">' +
            (v.limit.windows.length > 1 ? '<button type="button" class="z-remove" data-a="win-remove" data-v="' + i + '" aria-label="Zeitraum entfernen">×</button>' : "") + "</span></div>";
        });
        h += '<button type="button" class="z-row z-link" data-a="win-add">Weiteren Zeitraum hinzufügen</button>';
        h += '<div class="z-row z-stack"><span>An diesen Tagen</span>' + dayChips("limit-day", v.limit.days) + "</div>";
      }
    }
    h += '</div><div class="z-gfoot">' + (v.rotation
      ? "Wird " + durLabel(v.duration_minutes) + " lang gezeigt, dann folgt die nächste Ansicht." + (v.limit ? " Außerhalb der Zeiträume und Tage wird sie übersprungen." : "")
      : "Diese Ansicht wechselt sich nicht mit den anderen ab.") + "</div>";

    h += '<div class="z-ghead">Feste Zeiten</div><div class="z-group">' +
      v.fixed_times.map((f) => '<button type="button" class="z-row" data-a="fixed-open" data-v="' + esc(f.id) + '"><span class="z-grow"><span class="z-title">' + esc(rangeText(f)) + '</span><span class="z-meta">' +
        esc(f.date ? "Einmalig, " + shortDate(f.date) : daysSummary(f.days) + ((f.except_dates || []).length ? " · " + f.except_dates.length + " ausgesetzt" : "")) +
        '</span></span><span class="z-chev">›</span></button>').join("") +
      '<button type="button" class="z-row z-link" data-a="fixed-add">Feste Zeit hinzufügen</button></div>' +
      '<div class="z-gfoot">Während einer festen Zeit bleibt diese Ansicht auf dem Display, auch in der Ruhezeit.</div>';

    h += '<div class="z-ghead">Daten</div><div class="z-group"><div class="z-row"><span class="z-grow">Aktualisieren</span>' + refreshSelect(v) + "</div>" +
      ((v.refresh || {}).mode === "daily" ? '<div class="z-row"><span class="z-grow">Uhrzeit</span><input type="time" data-f="refresh.time" value="' + esc(v.refresh.time) + '" aria-label="Uhrzeit der Aktualisierung"></div>' : "") +
      '</div><div class="z-gfoot">' + esc(refreshFoot(v)) + "</div>";

    h += '<div class="z-group" style="margin-top:24px"><button type="button" class="z-row z-link" data-a="show-open">Jetzt anzeigen …</button>' +
      '<a class="z-row z-link" style="text-decoration:none" href="' + URLS.plugin + encodeURIComponent(v.plugin_id) + "?ansicht=" + encodeURIComponent(v.id) + '"><span class="z-grow">Plugin-Einstellungen</span><span class="z-chev">›</span></a></div>';
    h += '<div class="z-group" style="margin-top:24px">' + (sheet.confirmDelete
      ? '<div class="z-confirm"><span>„' + esc(v.name) + '“ wirklich löschen?</span><span><button type="button" class="z-btn" data-a="delete-cancel">Abbrechen</button> <button type="button" class="z-btn z-red" data-a="delete-confirm">Löschen</button></span></div>'
      : '<button type="button" class="z-row z-danger" data-a="delete-view">Ansicht löschen</button>') + "</div>";
    return h;
  }

  function pickViewHtml() {
    return head(["close", "Abbrechen"], "Feste Zeit ab " + hm(sheet.start)) +
      '<p class="z-gfoot" style="margin:0 4px 12px">Welche Ansicht soll dann zu sehen sein?</p>' +
      '<div class="z-group">' + schedule.views.map((v) => '<button type="button" class="z-row" data-a="pick-for-fixed" data-v="' + esc(v.id) + '">' + thumb(v) +
        '<span class="z-grow"><span class="z-title">' + esc(v.name) + '</span><span class="z-meta">' + esc(viewSummary(v)) + "</span></span></button>").join("") +
      '</div><div class="z-group" style="margin-top:12px"><button type="button" class="z-row z-link" data-a="add-view">Neue Ansicht anlegen …</button></div>';
  }

  function actionsHtml() {
    return '<div class="z-action-title">' + esc(sheet.title) + "</div>" +
      '<div class="z-group z-action">' + sheet.items.map((it, i) => '<button type="button" class="z-row" data-a="act" data-v="' + i + '">' + esc(it.label) + "</button>").join("") + "</div>" +
      '<div class="z-group z-action" style="margin-top:10px"><button type="button" class="z-row" data-a="close" style="font-weight:600">Abbrechen</button></div>';
  }

  function fixedHtml() {
    const f = sheet.fixed;
    let h = sheet.direct
      ? head(["close", "Abbrechen"], sheet.draft.name, ["fixed-save", sheet.fixedIsNew ? "Hinzufügen" : "Fertig"])
      : head(["fixed-cancel", "Zurück"], sheet.fixedIsNew ? "Feste Zeit" : "Feste Zeit bearbeiten", ["fixed-save", sheet.fixedIsNew ? "Hinzufügen" : "Übernehmen"]);
    if (sheet.direct) h += '<div class="z-hero"><img alt="" src="' + esc(plugin(sheet.draft.plugin_id).icon) + '"><span>Feste Zeit</span></div>';
    if (sheet.conflict) {
      const c = sheet.conflict;
      h += '<div class="z-notice z-warn"><strong>Überschneidet sich mit „' + esc(c.conf.v.name) + "“</strong> (" + esc(fixedSummary(c.conf.f)) + "). Wie soll es weitergehen?" +
        '<div class="z-resolve">' + c.opts.map((o, i) => '<button type="button" data-a="resolve" data-v="' + i + '">' + esc(o.label) + "</button>").join("") + "</div></div>";
    } else if (sheet.error) h += '<div class="z-notice z-warn">' + esc(sheet.error) + "</div>";
    h += '<div class="z-group" style="margin-top:12px"><div class="z-row"><span class="z-grow">Von</span><input type="time" data-f="fx.start" value="' + esc(f.start) + '" aria-label="Von"></div>' +
      '<div class="z-row"><span class="z-grow">Bis</span><input type="time" data-f="fx.end" value="' + esc(f.end) + '" aria-label="Bis"></div></div>' +
      '<div class="z-gfoot">Liegt das Ende vor dem Start, endet die feste Zeit am nächsten Tag.</div>';
    h += '<div class="z-ghead">Wiederholen</div><div class="z-group"><div class="z-row z-stack"><div class="z-seg"><button type="button" data-a="fx-mode" data-v="weekly" aria-pressed="' + (f.mode === "weekly") + '">Wöchentlich</button><button type="button" data-a="fx-mode" data-v="date" aria-pressed="' + (f.mode === "date") + '">Einmalig</button></div>';
    if (f.mode === "weekly") h += dayChips("fx-day", f.days) + '<div class="z-chips"><button type="button" class="z-chip" data-a="fx-preset" data-v="wk">Werktags</button><button type="button" class="z-chip" data-a="fx-preset" data-v="we">Wochenende</button><button type="button" class="z-chip" data-a="fx-preset" data-v="all">Täglich</button></div>';
    else h += '<div style="display:flex;align-items:center;gap:10px"><span class="z-grow">Datum</span><input type="date" data-f="fx.date" value="' + esc(f.date) + '" aria-label="Datum"></div>';
    h += "</div></div>";
    if (f.mode === "weekly" && f.except_dates.length) {
      h += '<div class="z-ghead">Ausgesetzt</div><div class="z-group">' + f.except_dates.map((k, i) => '<div class="z-row"><span class="z-grow">' + esc(shortDate(k)) + '</span><button type="button" class="z-btn" data-a="fx-unexcept" data-v="' + i + '">Wieder aufnehmen</button></div>').join("") + "</div>";
    }
    if (sheet.direct) h += touchedNote() + '<div class="z-group" style="margin-top:24px"><button type="button" class="z-row z-link" data-a="to-view">„' + esc(sheet.draft.name) + '“ bearbeiten …</button></div>';
    if (!sheet.fixedIsNew) h += '<div class="z-group" style="margin-top:24px"><button type="button" class="z-row z-danger" data-a="fixed-delete">Feste Zeit entfernen</button></div>';
    return h;
  }

  function showHtml() {
    const v = schedule.views.find((x) => x.id === sheet.viewId);
    const morning = schedule.quiet.enabled ? schedule.quiet.end : "06:00";
    return '<div class="z-action-title">„' + esc(v.name) + '“ jetzt anzeigen.<br>Danach geht es automatisch mit dem Zeitplan weiter.</div>' +
      '<div class="z-group z-action"><button type="button" class="z-row" data-a="show" data-v="1h">Für 1 Stunde</button><button type="button" class="z-row" data-a="show" data-v="morgen">Bis morgen früh (' + esc(morning) + ')</button><button type="button" class="z-row" data-a="show" data-v="immer">Bis ich es beende</button></div>' +
      '<div class="z-group z-action" style="margin-top:10px"><button type="button" class="z-row" data-a="show-back" style="font-weight:600">Abbrechen</button></div>';
  }

  // ---------- Aktionen ----------
  function openView(id) {
    const world = clone(schedule);
    const draft = world.views.find((v) => v.id === id);
    if (!draft) return;
    sheet = { mode: "view", world, draft, touched: new Set() };
    renderSheet();
  }
  function toggleIn(arr, x) { const i = arr.indexOf(x); if (i >= 0) arr.splice(i, 1); else arr.push(x); arr.sort((a, b) => a - b); }
  function clearIssue() { sheet.error = null; sheet.conflict = null; }
  function fail(msg) { sheet.error = msg; renderSheet(true); scrollToNotice(); }
  function scrollToNotice() { const n = document.querySelector(".z-sheet .z-notice"); if (n) n.scrollIntoView({ block: "nearest" }); }
  function backToView() {
    Object.assign(sheet, { mode: "view", fixed: null, error: null, conflict: null });
    renderSheet();
    const s = document.querySelector(".z-sheet");
    if (s) { s.style.animation = "none"; s.scrollTop = sheet.viewScroll || 0; }
  }

  // Feste Zeit direkt (von der Startseite): sofort sichern statt zurück in den Bearbeiten-Dialog
  async function commitDirect(message) {
    busy = true; renderSheet(true);
    try {
      await saveWorld(sheet.world);
      const names = [...sheet.touched];
      sheet = null; busy = false; renderSheet(); render();
      toast(message + (names.length ? " · " + names.map((n) => "„" + n + "“").join(", ") + " angepasst" : ""));
    } catch (e) { busy = false; fail(e.message); }
  }

  // check: sofort prüfen (z. B. nach dem Ziehen im Tagesplan), damit Überschneidungen gleich mit Vorschlägen erscheinen
  function openFixed(viewId, fixed, start, check) {
    const world = clone(schedule);
    const draft = world.views.find((v) => v.id === viewId);
    if (!draft) return;
    const isNew = !fixed || !draft.fixed_times.some((f) => f.id === fixed.id);
    const today = new Date();
    const draftFixed = fixed ? toDraft(fixed)
      : { id: uid("f"), start: hmS(start), end: hmS(Math.min(start + 60, 1440)), mode: "weekly", days: [wdOf(today)], date: dkey(today), except_dates: [] };
    sheet = { mode: "fixed", direct: true, world, draft, fixed: draftFixed, fixedIsNew: isNew, touched: new Set() };
    if (check) A["fixed-save"](); else renderSheet();
  }

  async function quickSave(world, message) {
    try { await saveWorld(world); render(); toast(message); }
    catch (e) { showResponseModal("failure", e.message); render(); }
  }

  const A = {
    "beta-on": async () => {
      try { await api("POST", URLS.beta, { enabled: true }); location.reload(); }
      catch (e) { showResponseModal("failure", e.message); }
    },
    "add-view": () => { sheet = { mode: "gallery" }; renderSheet(); },
    "open-view": (el) => openView(el.dataset.v),
    close: () => { sheet = null; renderSheet(); },
    scrim: (el, e) => { if (e.target === el) A.close(); },
    "default-dur": (el) => { const w = clone(schedule); w.default_duration_minutes = +el.dataset.v; quickSave(w, "Gesichert"); },
    "override-end": async () => {
      try { await api("DELETE", URLS.override); schedule.override = null; render(); toast("Es geht wieder nach Zeitplan weiter"); }
      catch (e) { showResponseModal("failure", e.message); }
    },

    dur: (el) => { sheet.draft.duration_minutes = +el.dataset.v; renderSheet(true); },
    "limit-day": (el) => { toggleIn(sheet.draft.limit.days, +el.dataset.v); renderSheet(true); },
    "win-add": () => { sheet.draft.limit.windows.push({ start: "17:00", end: "22:00" }); renderSheet(true); },
    "win-remove": (el) => { sheet.draft.limit.windows.splice(+el.dataset.v, 1); renderSheet(true); },
    "save-view": async () => {
      const v = sheet.draft;
      v.name = v.name.trim();
      if (!v.name) return fail("Bitte gib der Ansicht einen Namen.");
      if (v.limit && !v.limit.days.length) return fail("Wähle mindestens einen Tag für „Nur zu bestimmten Zeiten“.");
      if (v.limit && v.limit.windows.some((w) => w.start === w.end)) return fail("Ein Zeitraum braucht unterschiedliche Start- und Endzeiten.");
      busy = true; renderSheet(true);
      try {
        await saveWorld(sheet.world);
        const names = [...sheet.touched];
        sheet = null; busy = false; renderSheet(); render();
        toast("Gesichert" + (names.length ? " · " + names.map((n) => "„" + n + "“").join(", ") + " angepasst" : ""));
      } catch (e) { busy = false; fail(e.message); }
    },

    "fixed-add": () => {
      const s = document.querySelector(".z-sheet");
      Object.assign(sheet, { mode: "fixed", fixedIsNew: true, error: null, conflict: null, viewScroll: s ? s.scrollTop : 0,
        fixed: { id: uid("f"), start: "07:00", end: "08:00", mode: "weekly", days: [0, 1, 2, 3, 4], date: dkey(new Date()), except_dates: [] } });
      renderSheet();
    },
    "fixed-open": (el) => {
      const s = document.querySelector(".z-sheet");
      Object.assign(sheet, { mode: "fixed", fixedIsNew: false, error: null, conflict: null, viewScroll: s ? s.scrollTop : 0,
        fixed: toDraft(sheet.draft.fixed_times.find((f) => f.id === el.dataset.v)) });
      renderSheet();
    },
    "fixed-cancel": () => backToView(),
    "to-view": () => { Object.assign(sheet, { mode: "view", direct: false, fixed: null, conflict: null, error: null }); renderSheet(); },
    "pick-for-fixed": (el) => openFixed(el.dataset.v, null, sheet.start),
    act: (el) => { const item = sheet.items[+el.dataset.v]; sheet = null; renderSheet(); item.run(); },
    "fx-mode": (el) => { sheet.fixed.mode = el.dataset.v; clearIssue(); renderSheet(true); },
    "fx-day": (el) => { toggleIn(sheet.fixed.days, +el.dataset.v); clearIssue(); renderSheet(true); },
    "fx-preset": (el) => { sheet.fixed.days = { wk: [0, 1, 2, 3, 4], we: [5, 6], all: ALL_DAYS.slice() }[el.dataset.v]; clearIssue(); renderSheet(true); },
    "fx-unexcept": (el) => { sheet.fixed.except_dates.splice(+el.dataset.v, 1); renderSheet(true); },
    "fixed-save": () => {
      const f = sheet.fixed;
      clearIssue();
      if (!f.start || !f.end) return fail("Bitte gib Start und Ende an.");
      if (f.start === f.end) return fail("Start und Ende dürfen nicht gleich sein.");
      if (f.mode === "weekly" && !f.days.length) return fail("Wähle mindestens einen Tag.");
      if (f.mode === "date" && !f.date) return fail("Wähle ein Datum.");
      const res = resolutions(f, sheet.world);
      if (res) { sheet.conflict = res; renderSheet(true); scrollToNotice(); return; }
      const list = sheet.draft.fixed_times;
      const i = list.findIndex((x) => x.id === f.id);
      if (i >= 0) list[i] = asFixed(f); else list.push(asFixed(f));
      if (sheet.direct) commitDirect(sheet.fixedIsNew ? "Feste Zeit hinzugefügt" : "Gesichert");
      else backToView();
    },
    resolve: (el) => {
      const o = sheet.conflict.opts[+el.dataset.v];
      o.run();
      if (o.other && o.other !== sheet.draft) sheet.touched.add(o.other.name);
      A["fixed-save"]();
    },
    "fixed-delete": () => {
      sheet.draft.fixed_times = sheet.draft.fixed_times.filter((x) => x.id !== sheet.fixed.id);
      if (sheet.direct) commitDirect("Feste Zeit entfernt"); else backToView();
    },

    "show-open": () => { sheet = { mode: "show", viewId: sheet.draft.id, back: sheet }; renderSheet(); },
    "show-back": () => { sheet = sheet.back; renderSheet(); },
    show: async (el) => {
      const id = sheet.viewId;
      sheet = null; renderSheet();
      toast("Bild wird erzeugt …");
      try {
        const result = await api("POST", URLS.view + encodeURIComponent(id) + "/anzeigen", { bis: el.dataset.v });
        schedule.override = result.override; render();
        showResponseModal("success", result.message);
      } catch (e) { showResponseModal("failure", e.message); }
    },
    "delete-view": () => { sheet.confirmDelete = true; renderSheet(true); },
    "delete-cancel": () => { sheet.confirmDelete = false; renderSheet(true); },
    "delete-confirm": async () => {
      const v = sheet.draft;
      try {
        await api("DELETE", URLS.view + encodeURIComponent(v.id));
        schedule.views = schedule.views.filter((x) => x.id !== v.id);
        if (schedule.override && schedule.override.view_id === v.id) schedule.override = null;
        sheet = null; renderSheet(); render(); toast("„" + v.name + "“ gelöscht");
      } catch (e) { fail(e.message); }
    },
  };

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-a]");
    if (!el) return;
    // Links (z. B. Plugin-Kacheln) liegen im Sheet-Hintergrund, der selbst eine Aktion hat: normal öffnen lassen
    const link = e.target.closest("a[href]");
    if (link && el.contains(link)) return;
    const fn = A[el.dataset.a];
    if (fn) { e.preventDefault(); fn(el, e); }
  });

  document.addEventListener("change", (e) => {
    const el = e.target, f = el.dataset.f;
    if (!f) return;
    if (f.startsWith("quiet.")) {
      if (el.type !== "checkbox" && !el.value) return;
      const w = clone(schedule);
      w.quiet[f.slice(6)] = el.type === "checkbox" ? el.checked : el.value;
      quickSave(w, w.quiet.enabled ? "Ruhezeit gesichert" : "Ruhezeit aus");
      return;
    }
    if (!sheet) return;
    const v = sheet.draft;
    if (f === "rotation") { v.rotation = el.checked; renderSheet(true); }
    else if (f === "limit") { v.limit = el.checked ? { windows: [{ start: "06:00", end: "12:00" }], days: ALL_DAYS.slice() } : null; renderSheet(true); }
    else if (f === "refresh") {
      const val = el.value;
      v.refresh = val === "daily" ? { mode: "daily", time: (v.refresh && v.refresh.time) || "06:00" }
        : val.startsWith("i") ? { mode: "interval", minutes: +val.slice(1) } : { mode: val };
      renderSheet(true);
    }
  });

  document.addEventListener("input", (e) => {
    const el = e.target, f = el.dataset.f;
    if (!f || !sheet) return;
    const v = sheet.draft;
    if (f === "name") v.name = el.value;
    else if (f === "refresh.time" && el.value) v.refresh.time = el.value;
    else if (f.startsWith("win.") && el.value) v.limit.windows[+el.dataset.i][f.slice(4)] = el.value;
    else if (f.startsWith("fx.") && el.value) {
      sheet.fixed[f.slice(3)] = el.value;
      if (sheet.error || sheet.conflict) { clearIssue(); const n = document.querySelector(".z-sheet .z-notice.z-warn"); if (n) n.remove(); }
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !sheet) return;
    if (sheet.mode === "fixed" && !sheet.direct) backToView(); else A.close();
  });

  // Vorschaubilder: ohne erzeugtes Bild das Plugin-Symbol zeigen
  document.addEventListener("error", (e) => {
    const img = e.target;
    if (img.tagName === "IMG" && img.dataset.fallback && img.src !== img.dataset.fallback) {
      img.src = img.dataset.fallback;
      img.classList.add("z-icon");
      img.classList.remove("z-thumb");
    }
  }, true);

  // ---------- Sortieren per Ziehen ----------
  document.addEventListener("pointerdown", (e) => {
    const handle = e.target.closest("[data-handle]");
    if (!handle) return;
    e.preventDefault();
    const li = handle.closest(".z-row");
    const items = [...document.querySelectorAll("#zRotList .z-row[data-drag]")];
    const from = items.indexOf(li), h = li.getBoundingClientRect().height, y0 = e.clientY;
    let to = from;
    li.classList.add("z-dragging");
    handle.setPointerCapture(e.pointerId);
    const move = (ev) => {
      const dy = ev.clientY - y0;
      li.style.transform = "translateY(" + dy + "px)";
      to = Math.max(0, Math.min(items.length - 1, from + Math.round(dy / h)));
      items.forEach((it, i) => {
        if (it === li) return;
        let s = 0;
        if (from < to && i > from && i <= to) s = -h;
        if (from > to && i < from && i >= to) s = h;
        it.style.transform = s ? "translateY(" + s + "px)" : "";
      });
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      if (to === from) { render(); return; }
      const w = clone(schedule);
      const rot = w.views.filter((v) => v.rotation), rest = w.views.filter((v) => !v.rotation);
      const [moved] = rot.splice(from, 1);
      rot.splice(to, 0, moved);
      w.views = rot.concat(rest);
      quickSave(w, "Reihenfolge gesichert");
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  });

  // Für die Startseite (Tagesplan): Dialoge öffnen und über Änderungen informiert werden
  window.Zeitplan = {
    schedule: () => schedule,
    onChange: (cb) => listeners.push(cb),
    openView,
    openFixed,
    pickViewForFixed: (start) => { sheet = { mode: "pickview", start }; renderSheet(); },
    actions: (title, items) => { sheet = { mode: "actions", title, items }; renderSheet(); },
    findConflict: (fixed, world) => findConflict(fixed, world || schedule),
    save: async (world, message) => { await saveWorld(world); render(); if (message) toast(message); },
    endOverride: () => A["override-end"](),
    toast,
  };

  render();
  if (DATA.openView) openView(DATA.openView);
})();
