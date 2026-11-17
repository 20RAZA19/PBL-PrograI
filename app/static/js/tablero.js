/* Tablero de producción: la tarjeta solo muestra folio, cliente y tiempo restante.
 * Al tocarla se abre una ventana emergente con el detalle y las acciones.
 * Sin JavaScript (o con Ctrl/Cmd + clic) el enlace abre la página de rastreo completa. */
(function () {
    const modal = document.getElementById('kmodal');
    if (!modal || typeof modal.showModal !== 'function') return;

    let origen = null;

    function abrir(tarjeta) {
        const plantilla = document.getElementById(tarjeta.dataset.detalle);
        if (!plantilla) return false;
        modal.replaceChildren(plantilla.content.cloneNode(true));
        origen = tarjeta;
        modal.showModal();
        if (window.lucide) window.lucide.createIcons();
        const principal = modal.querySelector('.btn--primary') || modal.querySelector('[data-cerrar]');
        if (principal) principal.focus();
        return true;
    }

    document.addEventListener('click', (e) => {
        const tarjeta = e.target.closest('a.kcard[data-detalle]');
        if (!tarjeta) return;
        // Ctrl/Cmd/Shift + clic o clic central: dejar que abra la página en otra pestaña
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
        if (abrir(tarjeta)) e.preventDefault();
    });

    modal.addEventListener('click', (e) => {
        // Clic en el fondo oscuro (fuera del contenido) o en el botón de cerrar
        if (e.target === modal || e.target.closest('[data-cerrar]')) modal.close();
    });

    modal.addEventListener('close', () => {
        if (origen) origen.focus();
        origen = null;
    });
})();
