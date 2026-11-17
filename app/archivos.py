"""Subida de fotos de diseños e insumos.

Las imágenes se guardan en app/static/uploads/<carpeta>/ con un nombre
aleatorio y en la base de datos solo queda la ruta relativa a /static
(por ejemplo «uploads/disenos/3f2a….jpg»).
"""
import os
import uuid

from flask import current_app

EXTENSIONES = {"png", "jpg", "jpeg", "webp", "gif"}

# Firmas de los formatos permitidos: se revisa el contenido real del archivo,
# no solo la extensión del nombre.
_FIRMAS = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],
}


class ImagenInvalida(ValueError):
    pass


def _extension(nombre):
    return nombre.rsplit(".", 1)[-1].lower() if "." in (nombre or "") else ""


def _contenido_valido(cabecera, extension):
    if extension == "webp":
        return cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP"
    return any(cabecera.startswith(f) for f in _FIRMAS.get(extension, []))


def guardar_imagen(archivo, carpeta):
    """Valida y guarda un FileStorage. Devuelve la ruta relativa a /static."""
    if archivo is None or not getattr(archivo, "filename", ""):
        return None
    extension = _extension(archivo.filename)
    if extension not in EXTENSIONES:
        raise ImagenInvalida("Formato no permitido. Usa PNG, JPG, WEBP o GIF.")

    cabecera = archivo.stream.read(16)
    archivo.stream.seek(0)
    if not _contenido_valido(cabecera, extension):
        raise ImagenInvalida("El archivo no es una imagen válida.")

    destino = os.path.join(current_app.config["UPLOAD_FOLDER"], carpeta)
    os.makedirs(destino, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}.{'jpg' if extension == 'jpeg' else extension}"
    archivo.save(os.path.join(destino, nombre))
    return f"uploads/{carpeta}/{nombre}"


def eliminar_imagen(ruta):
    """Borra una imagen subida. Las imágenes que vienen con el proyecto no se tocan."""
    if not ruta or not ruta.startswith("uploads/"):
        return
    base = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    archivo = os.path.realpath(os.path.join(base, ruta[len("uploads/"):]))
    if archivo.startswith(base + os.sep) and os.path.isfile(archivo):
        os.remove(archivo)
