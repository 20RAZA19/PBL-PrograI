/* Utilidades de mapa para el módulo de rastreo (Leaflet + OpenStreetMap). */
(function () {
    'use strict';

    function icono(clase) {
        return L.divIcon({
            className: '',
            html: '<div class="' + clase + '"></div>',
            iconSize: [30, 30],
            iconAnchor: [15, 30],
            popupAnchor: [0, -28],
        });
    }

    const puntoRuta = L.divIcon({ className: '', html: '<div class="punto-ruta"></div>', iconSize: [12, 12], iconAnchor: [6, 6] });

    function crearMapa(elemento, centro, zoom) {
        const mapa = L.map(elemento, { scrollWheelZoom: false, zoomControl: true }).setView(centro, zoom || 12);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap',
        }).addTo(mapa);
        mapa.on('focus', () => mapa.scrollWheelZoom.enable());
        mapa.on('blur', () => mapa.scrollWheelZoom.disable());
        return mapa;
    }

    function escapar(texto) {
        const div = document.createElement('div');
        div.textContent = texto == null ? '' : String(texto);
        return div.innerHTML;
    }

    window.AyCMapa = {
        crearMapa: crearMapa,
        iconoActual: icono('pin pin--actual'),
        iconoPedido: icono('pin'),
        iconoTaller: icono('pin pin--taller'),
        puntoRuta: puntoRuta,
        escapar: escapar,
        colorRuta: function () {
            return getComputedStyle(document.documentElement).getPropertyValue('--c-fern').trim() || '#537B2F';
        },
    };
})();
