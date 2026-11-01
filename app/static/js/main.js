/**
 * Site-wide behaviour that must not live inline (Content-Security-Policy).
 * - Confirmation prompts for destructive forms
 * - Material ripple on interactive surfaces
 * - Top app bar elevation on scroll
 */
(function () {
    'use strict';

    // Confirmation prompts: <form data-confirm="Are you sure?">
    document.addEventListener('submit', function (event) {
        const form = event.target;
        if (form instanceof HTMLFormElement && form.dataset.confirm) {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        }
    });

    // Ripple (M3 state layer feedback) on buttons, list items and menu items.
    const RIPPLE_SELECTOR = '.btn, .list-group-item-action, .dropdown-item, .page-link, .nav-pills .nav-link, .service-card';
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.addEventListener('pointerdown', function (event) {
        if (reduceMotion || event.button !== 0) return;
        const target = event.target.closest(RIPPLE_SELECTOR);
        if (!target || target.disabled) return;
        const rect = target.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const ripple = document.createElement('span');
        ripple.className = 'md-ripple';
        ripple.style.width = ripple.style.height = size + 'px';
        ripple.style.left = (event.clientX - rect.left - size / 2) + 'px';
        ripple.style.top = (event.clientY - rect.top - size / 2) + 'px';
        target.appendChild(ripple);
        ripple.addEventListener('animationend', () => ripple.remove());
    });

    // Theme toggle (auto -> light -> dark), backed by theme.js.
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle && window.LexTheme) {
        const ICONS = { auto: 'brightness_auto', light: 'light_mode', dark: 'dark_mode' };
        const LABELS = { auto: 'automatic', light: 'light', dark: 'dark' };
        const render = (preference) => {
            const iconEl = themeToggle.querySelector('.material-symbols-outlined');
            if (iconEl) {
                iconEl.textContent = ICONS[preference];
                iconEl.className = `material-symbols-outlined icon icon-${ICONS[preference]}`;
            }
            themeToggle.setAttribute('aria-label', `Theme: ${LABELS[preference]}. Switch theme`);
        };
        render(window.LexTheme.get());
        themeToggle.addEventListener('click', () => render(window.LexTheme.cycle()));
    }

    // Top app bar: flat at the top of the page, elevated once content scrolls beneath it.
    const appBar = document.getElementById('top-app-bar');
    if (appBar) {
        const update = () => appBar.classList.toggle('is-scrolled', window.scrollY > 4);
        update();
        window.addEventListener('scroll', update, { passive: true });
    }
})();
