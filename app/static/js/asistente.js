/* Asistente AyC — interfaz del chat (el motor de respuestas corre en el servidor, sin APIs externas). */
(function () {
    'use strict';
    const raiz = document.getElementById('asistente');
    if (!raiz) return;

    const url = raiz.dataset.url;
    const claveHistorial = 'ayc-asistente-' + raiz.dataset.usuario;
    const panel = document.getElementById('asistente-panel');
    const abrir = document.getElementById('asistente-abrir');
    const cerrar = document.getElementById('asistente-cerrar');
    const limpiar = document.getElementById('asistente-limpiar');
    const lista = document.getElementById('asistente-mensajes');
    const chips = document.getElementById('asistente-chips');
    const form = document.getElementById('asistente-form');
    const input = document.getElementById('asistente-input');
    const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const chipsIniciales = chips.innerHTML;

    let historial = [];
    try { historial = JSON.parse(sessionStorage.getItem(claveHistorial) || '[]'); } catch (e) { historial = []; }

    function guardar() {
        try { sessionStorage.setItem(claveHistorial, JSON.stringify(historial.slice(-30))); } catch (e) { /* sin almacenamiento */ }
    }

    function el(tag, clase, texto) {
        const n = document.createElement(tag);
        if (clase) n.className = clase;
        if (texto != null) n.textContent = texto;
        return n;
    }

    function pintarMensaje(m) {
        const burbuja = el('div', 'asistente__msg asistente__msg--' + m.de);
        if (m.de === 'usuario') {
            burbuja.textContent = m.texto;
        } else {
            burbuja.appendChild(el('p', null, m.texto));
            if (m.pasos && m.pasos.length) {
                const ol = el('ol');
                m.pasos.forEach((p) => ol.appendChild(el('li', null, p)));
                burbuja.appendChild(ol);
            }
            if (m.nota) burbuja.appendChild(el('p', 'asistente__nota', m.nota));
            if (m.enlaces && m.enlaces.length) {
                const cont = el('div', 'asistente__enlaces');
                m.enlaces.forEach((e) => {
                    // Solo rutas internas del propio sistema
                    if (typeof e.url !== 'string' || e.url.charAt(0) !== '/' || e.url.charAt(1) === '/') return;
                    const a = el('a', null, e.texto + ' →');
                    a.href = e.url;
                    cont.appendChild(a);
                });
                burbuja.appendChild(cont);
            }
        }
        lista.appendChild(burbuja);
        lista.scrollTop = lista.scrollHeight;
    }

    function pintarChips(sugerencias) {
        chips.innerHTML = '';
        (sugerencias || []).slice(0, 4).forEach((s) => chips.appendChild(el('button', 'asistente__chip', s)));
        chips.hidden = !chips.children.length;
    }

    function bienvenida() {
        pintarMensaje({ de: 'bot', texto: '¡Hola! Soy el asistente de AyC Control. Pregúntame cómo hacer una gestión o qué opciones tienes con tu rol.' });
    }

    function render() {
        lista.innerHTML = '';
        bienvenida();
        historial.forEach(pintarMensaje);
    }

    function escribiendo(activo) {
        let ind = document.getElementById('asistente-escribiendo');
        if (activo && !ind) {
            ind = el('div', 'asistente__msg asistente__msg--bot asistente__escribiendo');
            ind.id = 'asistente-escribiendo';
            ind.innerHTML = '<span></span><span></span><span></span>';
            lista.appendChild(ind);
            lista.scrollTop = lista.scrollHeight;
        } else if (!activo && ind) {
            ind.remove();
        }
    }

    function preguntar(texto) {
        texto = (texto || '').trim();
        if (!texto) return;
        const mu = { de: 'usuario', texto: texto };
        historial.push(mu); pintarMensaje(mu); guardar();
        input.value = '';
        chips.hidden = true;
        escribiendo(true);

        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
            body: JSON.stringify({ mensaje: texto }),
        })
            .then((r) => r.ok ? r.json() : Promise.reject(r.status))
            .then((r) => {
                const mb = { de: 'bot', texto: r.texto, pasos: r.pasos, enlaces: r.enlaces, nota: r.nota };
                escribiendo(false);
                historial.push(mb); pintarMensaje(mb); guardar();
                pintarChips(r.sugerencias);
            })
            .catch(() => {
                escribiendo(false);
                pintarMensaje({ de: 'bot', texto: 'No pude responder en este momento. Recarga la página e inténtalo de nuevo.' });
            });
    }

    function alternar(mostrar) {
        panel.hidden = !mostrar;
        raiz.classList.toggle('asistente--abierto', mostrar);
        abrir.setAttribute('aria-expanded', String(mostrar));
        try { sessionStorage.setItem(claveHistorial + '-abierto', mostrar ? '1' : '0'); } catch (e) { /* nada */ }
        if (mostrar) { input.focus(); lista.scrollTop = lista.scrollHeight; }
    }

    abrir.addEventListener('click', () => alternar(panel.hidden));
    cerrar.addEventListener('click', () => alternar(false));
    limpiar.addEventListener('click', () => {
        historial = []; guardar(); render();
        chips.innerHTML = chipsIniciales; chips.hidden = false;
    });
    form.addEventListener('submit', (e) => { e.preventDefault(); preguntar(input.value); });
    chips.addEventListener('click', (e) => {
        if (e.target.classList.contains('asistente__chip')) preguntar(e.target.textContent);
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) alternar(false); });

    render();
    if (historial.length) chips.hidden = true;
    try { if (sessionStorage.getItem(claveHistorial + '-abierto') === '1') alternar(true); } catch (e) { /* nada */ }
})();
