/**
 * Site-wide behaviour that must not live inline (Content-Security-Policy).
 */
(function () {
    'use strict';

    // Confirmation prompts for destructive forms: <form data-confirm="Are you sure?">
    document.addEventListener('submit', function (event) {
        const form = event.target;
        if (form instanceof HTMLFormElement && form.dataset.confirm) {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        }
    });
})();
