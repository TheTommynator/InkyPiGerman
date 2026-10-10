/**
 * Erscheinungsbild: folgt standardmäßig dem Gerät (hell/dunkel).
 * In den Einstellungen lässt sich „Hell“ oder „Dunkel“ fest wählen (localStorage).
 */
(function initTheme() {
    const THEME_KEY = 'inkypi-theme';
    const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function stored() {
        try {
            const value = localStorage.getItem(THEME_KEY);
            return value === 'light' || value === 'dark' ? value : 'auto';
        } catch (e) {
            return 'auto';
        }
    }

    function apply() {
        const choice = stored();
        const dark = choice === 'dark' || (choice === 'auto' && media && media.matches);
        if (dark) {
            document.documentElement.setAttribute('data-theme', 'dark');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
    }

    function set(choice) {
        try {
            if (choice === 'light' || choice === 'dark') {
                localStorage.setItem(THEME_KEY, choice);
            } else {
                localStorage.removeItem(THEME_KEY);
            }
        } catch (e) {}
        apply();
    }

    apply();
    if (media) {
        media.addEventListener('change', apply);
    }

    window.InkyTheme = { get: stored, set };
})();
