/* Gráficos del dashboard con Chart.js.
 * Los datos vienen del servidor en <script id="datos-graficos" type="application/json">.
 * Los colores se leen de las variables CSS, así respetan el modo claro/oscuro. */
(function () {
    const nodo = document.getElementById('datos-graficos');
    if (!nodo) return;
    const datos = JSON.parse(nodo.textContent);
    const lienzos = ['grafico-pedidos', 'grafico-prendas', 'grafico-consumo', 'grafico-finanzas']
        .map((id) => document.getElementById(id)).filter(Boolean);

    // Sin conexión a internet no carga la librería: se muestra un aviso con los datos en texto
    if (typeof window.Chart === 'undefined') {
        lienzos.forEach((c) => {
            const aviso = document.createElement('p');
            aviso.className = 'grafico__aviso';
            aviso.textContent = 'No se pudo cargar la librería de gráficos (se necesita conexión a internet).';
            c.replaceWith(aviso);
        });
        return;
    }

    const numero = new Intl.NumberFormat('es-SV', { maximumFractionDigits: 0 });
    const moneda = new Intl.NumberFormat('es-SV', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
    let graficos = [];

    function color(variable, respaldo) {
        const v = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
        return v || respaldo;
    }

    function conAlfa(hex, alfa) {
        const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
        if (!m) return hex;
        const n = parseInt(m[1], 16);
        return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alfa})`;
    }

    // Las telas muy claras (blanco, celeste) se ven mal sobre fondo blanco: se oscurecen un poco
    function visible(hex) {
        const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
        if (!m) return '#888888';
        const n = parseInt(m[1], 16);
        const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
        const luz = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        if (luz < 0.82) return '#' + m[1];
        const f = 0.62;
        return '#' + [r, g, b].map((x) => Math.round(x * f).toString(16).padStart(2, '0')).join('');
    }

    function base() {
        const texto = color('--text-muted', '#64748b');
        const rejilla = color('--border-color', '#e2e8f0');
        Chart.defaults.font.family = '"Inter", system-ui, sans-serif';
        Chart.defaults.color = texto;
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, padding: 16 } },
                tooltip: { padding: 10, cornerRadius: 8 },
            },
            scales: {
                x: { grid: { display: false }, border: { color: rejilla } },
                y: { beginAtZero: true, grid: { color: rejilla }, border: { display: false },
                     ticks: { precision: 0 } },
            },
        };
    }

    function dibujar() {
        graficos.forEach((g) => g.destroy());
        graficos = [];
        const primario = color('--serie-1', '#2f7a26');
        const secundario = color('--serie-2', '#2a78d6');
        const acento = color('--serie-3', '#eb6834');
        const superficie = color('--bg-panel', '#ffffff');
        const tramo = datos.etiquetas.length;

        // 1. Pedidos recibidos y entregados (un solo eje: las prendas van en su propio gráfico)
        const cPed = document.getElementById('grafico-pedidos');
        if (cPed) {
            const op = base();
            op.scales.y.title = { display: true, text: 'Pedidos' };
            graficos.push(new Chart(cPed, {
                type: 'bar',
                data: {
                    labels: datos.etiquetas,
                    datasets: [
                        { label: 'Recibidos', data: datos.pedidos.recibidos, backgroundColor: primario,
                          borderRadius: 4, maxBarThickness: 26 },
                        { label: 'Entregados', data: datos.pedidos.entregados, backgroundColor: secundario,
                          borderRadius: 4, maxBarThickness: 26 },
                    ],
                },
                options: op,
            }));
        }

        // 1b. Prendas recibidas
        const cPre = document.getElementById('grafico-prendas');
        if (cPre) {
            const op = base();
            op.plugins.legend.display = false;
            op.plugins.tooltip.callbacks = { label: (c) => ` Prendas: ${numero.format(c.parsed.y)}` };
            graficos.push(new Chart(cPre, {
                type: 'line',
                data: { labels: datos.etiquetas, datasets: [{
                    label: 'Prendas recibidas', data: datos.pedidos.prendas, borderColor: primario,
                    backgroundColor: conAlfa(primario, 0.08), fill: 'origin', borderWidth: 2, tension: 0.3,
                    pointRadius: tramo > 16 ? 0 : 4, pointBorderColor: superficie, pointBorderWidth: 2 }] },
                options: op,
            }));
        }

        // 2. Consumo de telas: una línea por tela (colores de serie en orden fijo) + total punteado
        const cCon = document.getElementById('grafico-consumo');
        if (cCon) {
            const op = base();
            op.scales.y.ticks = { callback: (v) => numero.format(v) + ' m' };
            op.plugins.tooltip.callbacks = { label: (c) => ` ${c.dataset.label}: ${numero.format(c.parsed.y)} m` };
            const series = datos.consumo.series.map((s, i) => ({
                type: 'line', label: s.nombre, data: s.valores, borderColor: color('--serie-' + (i + 1), '#888'),
                backgroundColor: color('--serie-' + (i + 1), '#888'), tension: 0.3, pointRadius: tramo > 16 ? 0 : 3,
                borderWidth: 2,
            }));
            series.push({ type: 'line', label: 'Total telas', data: datos.consumo.total,
                          borderColor: color('--text-muted', '#64748b'), borderDash: [6, 6], pointRadius: 0,
                          borderWidth: 2, tension: 0.3 });
            graficos.push(new Chart(cCon, { type: 'line', data: { labels: datos.etiquetas, datasets: series }, options: op }));
        }

        // 3. Ventas y ganancia (solo Administración y Ventas)
        const cFin = document.getElementById('grafico-finanzas');
        if (cFin && datos.finanzas) {
            const op = base();
            op.scales.y.ticks = { callback: (v) => moneda.format(v) };
            op.plugins.tooltip.callbacks = { label: (c) => ` ${c.dataset.label}: ${moneda.format(c.parsed.y)}` };
            graficos.push(new Chart(cFin, {
                type: 'bar',
                data: {
                    labels: datos.etiquetas,
                    datasets: [
                        { type: 'bar', label: 'Ventas (pedidos recibidos)', data: datos.finanzas.ingresos,
                          backgroundColor: primario, borderRadius: 4, maxBarThickness: 34, order: 2 },
                        { type: 'line', label: 'Ganancia estimada', data: datos.finanzas.ganancias,
                          borderColor: acento, backgroundColor: acento, tension: 0.3, borderWidth: 2,
                          pointRadius: tramo > 16 ? 0 : 4, pointBorderColor: superficie, pointBorderWidth: 2, order: 1 },
                    ],
                },
                options: op,
            }));
        }
    }

    dibujar();
    document.addEventListener('ayc:tema', dibujar);
})();
