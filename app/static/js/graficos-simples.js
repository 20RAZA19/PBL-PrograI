/* Gráficos declarativos de AyC Control.
 *
 * Cualquier página puede poner un gráfico con el macro `grafico()` de _macros.html:
 *   <canvas data-grafico="id-de-los-datos">  +  <script type="application/json" id="id-de-los-datos">{...}</script>
 *
 * Formato de los datos:
 *   { "tipo": "barras" | "barras-h" | "linea" | "dona",
 *     "etiquetas": ["Ene", "Feb", ...],
 *     "series": [{ "nombre": "Recibidos", "valores": [1, 2, ...], "color": "serie-1" | "ok" | "warn" | "danger" | "neutral" }],
 *     "unidad": "prendas", "moneda": false, "apilado": false, "porcentaje": false }
 *
 * Los colores salen de variables CSS (--serie-1… y los de estado), así siguen el modo claro/oscuro.
 * El color sigue a la serie (no a su posición), y cada gráfico trae su tabla en «Ver datos».
 */
(function () {
    const lienzos = Array.from(document.querySelectorAll('canvas[data-grafico]'));
    if (!lienzos.length) return;

    if (typeof window.Chart === 'undefined') {
        lienzos.forEach((c) => {
            const aviso = document.createElement('p');
            aviso.className = 'grafico__aviso';
            aviso.textContent = 'No se pudo cargar la librería de gráficos. Abre «Ver datos» para ver las cifras.';
            c.replaceWith(aviso);
        });
        return;
    }

    const numero = new Intl.NumberFormat('es-SV', { maximumFractionDigits: 1 });
    const moneda = new Intl.NumberFormat('es-SV', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
    const ESTADOS = { ok: '--estado-ok', warn: '--estado-warn', danger: '--estado-danger', neutral: '--estado-neutral' };
    let activos = [];

    function css(nombre, respaldo) {
        const v = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
        return v || respaldo;
    }

    function colorDe(serie, i) {
        const clave = serie.color || `serie-${(i % 5) + 1}`;
        if (clave.startsWith('#')) return clave;
        return css(ESTADOS[clave] || `--${clave}`, '#2f7a26');
    }

    function formato(d, v) {
        if (v === null || v === undefined) return '—';
        if (d.moneda) return moneda.format(v);
        if (d.porcentaje) return numero.format(v) + ' %';
        return numero.format(v) + (d.unidad ? ' ' + d.unidad : '');
    }

    function opciones(d, nSeries) {
        const texto = css('--text-muted', '#64748b');
        const rejilla = css('--border-color', '#e2e8f0');
        const superficie = css('--bg-panel', '#ffffff');
        Chart.defaults.font.family = '"Inter", system-ui, sans-serif';
        Chart.defaults.color = texto;
        const horizontal = d.tipo === 'barras-h';
        const op = {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: d.tipo === 'dona' ? 'nearest' : 'index', intersect: d.tipo === 'dona' },
            plugins: {
                legend: { display: nSeries > 1 || d.tipo === 'dona', position: 'bottom',
                          labels: { usePointStyle: true, boxWidth: 8, padding: 14 } },
                tooltip: { padding: 10, cornerRadius: 8,
                           callbacks: { label: (c) => ` ${c.dataset.label || c.label}: ${formato(d, c.raw)}` } },
            },
        };
        if (d.tipo === 'dona') {
            op.cutout = '62%';
            op.plugins.tooltip.callbacks.label = (c) => ` ${c.label}: ${formato(d, c.raw)}`;
            op.borderColor = superficie;
            return op;
        }
        const valor = { beginAtZero: true, grid: { color: rejilla }, border: { display: false },
                        ticks: { precision: 0, callback: (v) => (d.moneda ? moneda.format(v) : numero.format(v)) },
                        stacked: !!d.apilado };
        if (d.porcentaje) { valor.max = 100; valor.ticks.callback = (v) => v + ' %'; }
        const categoria = { grid: { display: false }, border: { color: rejilla }, stacked: !!d.apilado,
                            ticks: { autoSkip: true, maxRotation: 0 } };
        op.indexAxis = horizontal ? 'y' : 'x';
        op.scales = horizontal ? { x: valor, y: categoria } : { x: categoria, y: valor };
        return op;
    }

    function conjunto(d, serie, i) {
        const color = colorDe(serie, i);
        const superficie = css('--bg-panel', '#ffffff');
        if (d.tipo === 'dona') {
            const colores = serie.colores
                ? serie.colores.map((c, j) => colorDe({ color: c }, j))
                : serie.valores.map((_, j) => colorDe({}, j));
            return { label: serie.nombre, data: serie.valores, backgroundColor: colores,
                     borderColor: superficie, borderWidth: 2, hoverOffset: 4 };
        }
        if (d.tipo === 'linea') {
            return { label: serie.nombre, data: serie.valores, borderColor: color, backgroundColor: color,
                     borderWidth: 2, tension: serie.escalonada ? 0 : 0.3, stepped: serie.escalonada ? 'before' : false,
                     pointRadius: serie.valores.length > 16 ? 0 : 4,
                     pointHoverRadius: 5, pointBorderColor: superficie, pointBorderWidth: 2,
                     borderDash: serie.punteada ? [6, 5] : undefined };
        }
        // Barras: un color por barra si la serie lo pide (estados), con 2 px de separación del fondo.
        const fondo = serie.colores ? serie.colores.map((c, j) => colorDe({ color: c }, j)) : color;
        return { label: serie.nombre, data: serie.valores, backgroundColor: fondo,
                 borderColor: superficie, borderWidth: d.apilado ? { top: 2 } : 0,
                 borderRadius: 4, borderSkipped: 'start', maxBarThickness: 34 };
    }

    function dibujar() {
        activos.forEach((g) => g.destroy());
        activos = [];
        lienzos.forEach((lienzo) => {
            const nodo = document.getElementById(lienzo.dataset.grafico);
            if (!nodo) return;
            const d = JSON.parse(nodo.textContent);
            const series = (d.series || []).filter((s) => s.valores && s.valores.length);
            const tipo = { 'barras': 'bar', 'barras-h': 'bar', 'linea': 'line', 'dona': 'doughnut' }[d.tipo] || 'bar';
            activos.push(new Chart(lienzo, {
                type: tipo,
                data: { labels: d.etiquetas, datasets: series.map((s, i) => conjunto(d, s, i)) },
                options: opciones(d, series.length),
            }));
        });
    }

    dibujar();
    document.addEventListener('ayc:tema', dibujar);
})();
