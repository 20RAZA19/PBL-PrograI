/* Mensajería asistente–cliente: envía sin recargar y trae los mensajes nuevos cada pocos segundos. */
(function () {
    'use strict';
    const chat = document.getElementById('chat');
    if (!chat) return;
    const lista = document.getElementById('chat-mensajes');
    const form = document.getElementById('chat-form');
    const texto = document.getElementById('chat-texto');
    const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const url = chat.dataset.url;
    const refresco = Math.max(3, parseInt(chat.dataset.refresco || '8', 10)) * 1000;
    const soyCliente = chat.dataset.lado === 'cliente';
    let ultimo = parseInt(chat.dataset.ultimo || '0', 10);
    let ocupado = false;

    function abajo() { lista.scrollTop = lista.scrollHeight; }

    function pintar(m) {
        if (lista.querySelector('[data-id="' + m.id + '"]')) return;
        const mio = m.de_cliente === soyCliente;
        const d = document.createElement('div');
        d.className = 'chat__msg ' + (mio ? 'chat__msg--mio' : 'chat__msg--otro');
        d.dataset.id = m.id;
        const a = document.createElement('span');
        a.className = 'chat__autor';
        a.textContent = m.autor + ' · ' + m.hora;
        const p = document.createElement('p');
        p.textContent = m.texto;
        d.appendChild(a); d.appendChild(p);
        lista.appendChild(d);
        if (m.id > ultimo) ultimo = m.id;
    }

    async function traer() {
        if (ocupado || document.hidden) return;
        ocupado = true;
        try {
            const r = await fetch(url + '?desde=' + ultimo, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' });
            if (r.ok) {
                const datos = await r.json();
                const habia = ultimo;
                (datos.mensajes || []).forEach(pintar);
                if (ultimo !== habia) abajo();
            }
        } catch (e) { /* sin conexión: se reintenta en el siguiente ciclo */ }
        ocupado = false;
    }

    form.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        const valor = texto.value.trim();
        if (!valor) return;
        const datos = new FormData(form);
        try {
            const r = await fetch(form.action, { method: 'POST', body: datos, credentials: 'same-origin',
                                                 headers: { 'Accept': 'application/json', 'X-CSRFToken': csrf } });
            if (!r.ok) { form.submit(); return; }
            const res = await r.json();
            if (res && res.mensaje) { pintar(res.mensaje); abajo(); }
            texto.value = '';
            texto.focus();
        } catch (e) { form.submit(); }
    });

    texto.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); }
    });

    abajo();
    setInterval(traer, refresco);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) traer(); });
})();
