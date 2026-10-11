// Status der Display-Aktualisierung auf allen Seiten.
// Fragt /api/display_status ab, zeigt den laufenden Schritt samt Fortschritt in einer
// schwebenden Leiste und meldet jeden neuen Stand als Ereignis „display-status“
// (die Startseite nutzt das für ihre eigene Anzeige unter dem Bild).
(function() {
    const BUSY_INTERVAL_MS = 1000;
    const IDLE_INTERVAL_MS = 4000;
    const DONE_VISIBLE_MS = 4000;

    let url = null;
    let status = null;
    let received = 0;
    let timer = null;
    let doneUntil = 0;
    let dismissedError = null;

    function formatDuration(seconds) {
        seconds = Math.max(0, Math.round(seconds));
        if (seconds < 60) return `${seconds} s`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes} Min.`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours} Std.`;
        const days = Math.floor(hours / 24);
        return days === 1 ? '1 Tag' : `${days} Tagen`;
    }

    // Fortschritt hochgerechnet auf jetzt: {fraction (0–1 oder null), remaining (s oder null), elapsed}
    function progress(s) {
        const passed = (Date.now() - received) / 1000;
        if (!s || !s.refreshing) return {fraction: null, remaining: null, elapsed: 0};
        const elapsed = s.elapsed_seconds + passed;
        let remaining = null;
        if (s.remaining_seconds !== null && s.remaining_seconds !== undefined) {
            remaining = s.remaining_seconds - passed;
        } else if (s.expected_seconds) {
            remaining = s.expected_seconds - elapsed;
        }
        if (remaining === null) return {fraction: null, remaining: null, elapsed};
        const fraction = Math.min(1, elapsed / Math.max(0.1, elapsed + Math.max(0, remaining)));
        return {fraction, remaining, elapsed};
    }

    // Texte für den aktuellen Stand: {title, phase, detail}
    function describe(s) {
        const p = progress(s);
        let phase = s.phase || 'Wird aktualisiert';
        if (s.step && s.steps) phase = `${phase} (${s.step}/${s.steps})`;
        let detail = '';
        if (s.refreshing) {
            if (p.remaining === null) detail = `seit ${formatDuration(p.elapsed)}`;
            else if (p.remaining > 1) detail = `noch ca. ${formatDuration(p.remaining)}`;
            else detail = 'gleich fertig';
        }
        return {title: s.title, phase, detail, fraction: p.fraction};
    }

    function render() {
        const box = document.getElementById('globalDisplayStatus');
        if (!box || !status) return;
        const title = box.querySelector('.gds-title');
        const text = box.querySelector('.gds-text');
        const bar = box.querySelector('.gds-bar');
        const fill = box.querySelector('.gds-fill');
        const close = box.querySelector('.gds-close');

        box.classList.remove('busy', 'done', 'failed', 'indeterminate');
        if (status.busy) {
            const d = describe(status);
            box.classList.add('busy');
            title.textContent = d.title ? `Display: ${d.title}` : 'Display';
            text.textContent = d.detail ? `${d.phase} · ${d.detail}` : `${d.phase} …`;
            bar.hidden = false;
            if (d.fraction === null) box.classList.add('indeterminate');
            else fill.style.width = `${Math.round(d.fraction * 100)}%`;
            close.hidden = true;
            box.hidden = false;
        } else if (status.error && status.error !== dismissedError) {
            box.classList.add('failed');
            title.textContent = 'Display';
            text.textContent = `Fehler: ${status.error}`;
            bar.hidden = true;
            close.hidden = false;
            box.hidden = false;
        } else if (Date.now() < doneUntil) {
            box.classList.add('done');
            title.textContent = 'Display';
            text.textContent = 'Neues Bild ist zu sehen';
            bar.hidden = false;
            fill.style.width = '100%';
            close.hidden = true;
            box.hidden = false;
        } else {
            box.hidden = true;
        }
    }

    function schedule() {
        clearTimeout(timer);
        if (document.hidden) return;
        timer = setTimeout(poll, status && status.busy ? BUSY_INTERVAL_MS : IDLE_INTERVAL_MS);
    }

    async function poll() {
        try {
            const response = await fetch(url, {cache: 'no-store'});
            if (response.ok) {
                const wasRefreshing = status && status.refreshing;
                status = await response.json();
                received = Date.now();
                if (wasRefreshing && !status.refreshing && !status.error) doneUntil = Date.now() + DONE_VISIBLE_MS;
                render();
                document.dispatchEvent(new CustomEvent('display-status', {
                    detail: {status, finished: wasRefreshing && !status.refreshing},
                }));
            }
        } catch (error) {
            console.error('Display-Status nicht abrufbar:', error);
        }
        schedule();
    }

    function start(statusUrl) {
        url = statusUrl;
        try { dismissedError = sessionStorage.getItem('inkypi-status-dismissed'); } catch (e) {}
        const box = document.getElementById('globalDisplayStatus');
        if (box) {
            box.querySelector('.gds-close').addEventListener('click', function() {
                dismissedError = status && status.error;
                try { sessionStorage.setItem('inkypi-status-dismissed', dismissedError || ''); } catch (e) {}
                render();
            });
        }
        document.addEventListener('visibilitychange', function() {
            if (!document.hidden) poll();
        });
        poll();
        // Restzeit zwischen den Abfragen weiterzählen
        setInterval(function() {
            render();
            if (status) document.dispatchEvent(new CustomEvent('display-status-tick', {detail: {status}}));
        }, 1000);
    }

    // Seiten können sofort nachfragen, z. B. direkt nach „Jetzt anzeigen“
    function refresh() {
        if (url) poll();
    }

    // Nach jedem Speichern/Anzeigen (POST & Co.) gleich nachsehen, ob das Display jetzt arbeitet
    const originalFetch = window.fetch;
    if (originalFetch) {
        window.fetch = function(resource, options) {
            const result = originalFetch.apply(this, arguments);
            const method = ((options && options.method) || (resource && resource.method) || 'GET').toUpperCase();
            if (method !== 'GET' && method !== 'HEAD') {
                result.then(refresh, function() {});
            }
            return result;
        };
    }

    window.DisplayStatus = {start, refresh, describe, progress, formatDuration, current: () => status, received: () => received};
})();
