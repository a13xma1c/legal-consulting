/**
 * LexCounsel AI chat client.
 *
 * Powers both the floating widget (#chat-widget) and the full-page chat
 * (#chat-page). Each root element must expose data-history-url,
 * data-message-url and data-reset-url, and contain [data-chat-messages] and
 * [data-chat-form].
 */
(function () {
    'use strict';

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async function api(url, body) {
        const response = await fetch(url, {
            method: body === undefined ? 'GET' : 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            credentials: 'same-origin',
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        let data = {};
        try { data = await response.json(); } catch (_) { /* non-JSON error */ }
        if (!response.ok) {
            throw new Error(data.error || `Request failed (${response.status})`);
        }
        return data;
    }

    class Chat {
        constructor(root) {
            this.root = root;
            this.urls = {
                history: root.dataset.historyUrl,
                message: root.dataset.messageUrl,
                reset: root.dataset.resetUrl,
            };
            this.messagesEl = root.querySelector('[data-chat-messages]');
            this.form = root.querySelector('[data-chat-form]');
            this.input = this.form.querySelector('[name="message"]');
            this.button = this.form.querySelector('button[type="submit"]');
            this.loaded = this.messagesEl.children.length > 0;
            this.busy = false;

            this.form.addEventListener('submit', (e) => { e.preventDefault(); this.send(); });
            if (this.input.tagName === 'TEXTAREA') {
                this.input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.send(); }
                });
                this.input.addEventListener('input', () => this.autosize());
            }
            if (this.loaded) this.scrollToBottom();
        }

        autosize() {
            this.input.style.height = 'auto';
            this.input.style.height = Math.min(this.input.scrollHeight, 160) + 'px';
        }

        scrollToBottom() {
            this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        }

        addMessage(role, html, { raw = false } = {}) {
            const wrapper = document.createElement('div');
            wrapper.className = `chat-msg chat-msg-${role}`;
            const bubble = document.createElement('div');
            bubble.className = 'chat-bubble markdown-body';
            if (raw) bubble.textContent = html; else bubble.innerHTML = html;
            wrapper.appendChild(bubble);
            this.messagesEl.appendChild(wrapper);
            this.scrollToBottom();
            return wrapper;
        }

        addTyping() {
            const el = this.addMessage('assistant', '<span class="chat-typing"><span></span><span></span><span></span></span>');
            el.classList.add('chat-msg-typing');
            return el;
        }

        async loadHistory() {
            if (this.loaded) return;
            this.loaded = true;
            try {
                const data = await api(this.urls.history);
                if (!data.messages.length) {
                    this.addMessage('assistant', '<p>Hello! I\'m the LexCounsel assistant. Ask me a general legal question and I\'ll help you understand your options.</p>');
                } else {
                    data.messages.forEach((m) => this.addMessage(m.role, m.html));
                }
            } catch (err) {
                this.addMessage('error', escapeHtml(err.message));
            }
        }

        setBusy(state) {
            this.busy = state;
            this.button.disabled = state;
            this.input.disabled = state;
        }

        async send(text) {
            text = (text ?? this.input.value).trim();
            if (!text || this.busy) return;
            this.input.value = '';
            if (this.input.tagName === 'TEXTAREA') this.autosize();
            this.addMessage('user', escapeHtml(text).replace(/\n/g, '<br>'));
            this.setBusy(true);
            const typing = this.addTyping();
            try {
                const data = await api(this.urls.message, { message: text });
                typing.remove();
                this.addMessage('assistant', data.reply.html);
            } catch (err) {
                typing.remove();
                this.addMessage('error', escapeHtml(err.message));
            } finally {
                this.setBusy(false);
                this.input.focus();
            }
        }

        async reset() {
            try {
                await api(this.urls.reset, {});
                this.messagesEl.innerHTML = '';
                this.loaded = false;
                await this.loadHistory();
            } catch (err) {
                this.addMessage('error', escapeHtml(err.message));
            }
        }
    }

    // ----- Floating widget ------------------------------------------------
    const widgetRoot = document.getElementById('chat-widget');
    if (widgetRoot) {
        const chat = new Chat(widgetRoot);
        const toggle = widgetRoot.querySelector('.chat-widget-toggle');
        const panel = widgetRoot.querySelector('.chat-widget-panel');
        const close = widgetRoot.querySelector('.chat-widget-close');

        const open = () => {
            panel.hidden = false;
            toggle.setAttribute('aria-expanded', 'true');
            chat.loadHistory();
            chat.input.focus();
        };
        const hide = () => {
            panel.hidden = true;
            toggle.setAttribute('aria-expanded', 'false');
        };
        toggle.addEventListener('click', () => (panel.hidden ? open() : hide()));
        close.addEventListener('click', hide);
    }

    // ----- Full page ------------------------------------------------------
    const pageRoot = document.getElementById('chat-page');
    if (pageRoot) {
        const chat = new Chat(pageRoot);
        chat.loadHistory();
        chat.input.focus();

        document.querySelector('[data-chat-reset]')?.addEventListener('click', () => chat.reset());
        document.querySelectorAll('[data-suggestion]').forEach((btn) => {
            btn.addEventListener('click', () => chat.send(btn.textContent.trim()));
        });
    }
})();
