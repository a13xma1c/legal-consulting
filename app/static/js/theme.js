/**
 * Theme selection (light / dark / auto) - loaded synchronously in <head> so the
 * correct scheme is applied before first paint. Inline scripts are blocked by
 * the Content-Security-Policy, hence a separate file.
 *
 * The resolved scheme is written to <html data-bs-theme="..."> (which Bootstrap
 * also reads) and the user's preference to data-theme-preference.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'lexcounsel-theme';
    var ORDER = ['auto', 'light', 'dark'];
    var THEME_COLORS = { light: '#1e3a6e', dark: '#111318' };
    var root = document.documentElement;
    var media = window.matchMedia('(prefers-color-scheme: dark)');

    function stored() {
        try {
            var value = localStorage.getItem(STORAGE_KEY);
            return ORDER.indexOf(value) === -1 ? 'auto' : value;
        } catch (_) {
            return 'auto';
        }
    }

    function resolve(preference) {
        return preference === 'auto' ? (media.matches ? 'dark' : 'light') : preference;
    }

    function apply(preference) {
        var scheme = resolve(preference);
        root.setAttribute('data-bs-theme', scheme);
        root.setAttribute('data-theme-preference', preference);
        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute('content', THEME_COLORS[scheme]);
        root.dispatchEvent(new CustomEvent('themechange', { detail: { preference: preference, scheme: scheme } }));
        return scheme;
    }

    apply(stored());
    media.addEventListener('change', function () {
        if (stored() === 'auto') apply('auto');
    });

    window.LexTheme = {
        get: stored,
        resolve: function () { return resolve(stored()); },
        set: function (preference) {
            try { localStorage.setItem(STORAGE_KEY, preference); } catch (_) { /* private mode */ }
            return apply(preference);
        },
        cycle: function () {
            var next = ORDER[(ORDER.indexOf(stored()) + 1) % ORDER.length];
            this.set(next);
            return next;
        },
    };
})();
