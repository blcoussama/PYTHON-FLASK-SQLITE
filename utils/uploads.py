"""Enregistrement et suppression des images d'articles.

Une image envoyée n'est jamais copiée telle quelle : Pillow vérifie qu'il
s'agit vraiment d'un PNG ou d'un JPEG, puis l'image est ré-encodée sous un
nom aléatoire. Le fichier stocké ne contient donc ni code caché (HTML, script)
ni métadonnées (EXIF, position GPS), et son nom ne dépend pas de l'utilisateur.
"""
import logging
import os
import re
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}
# Format détecté par Pillow -> extension du fichier enregistré
_FORMATS = {"PNG": "png", "JPEG": "jpg"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024   # 5 Mo, comme le contrôle côté navigateur
MAX_PIXELS = 25_000_000             # protège contre les « bombes de décompression »
# Seuls les noms générés par save_image() sont servis ou supprimés.
STORED_NAME = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg)$")

INVALID_TYPE = "Type de fichier invalide. Seuls PNG/JPG/JPEG sont autorisés."
INVALID_CONTENT = "Le fichier n'est pas une image PNG ou JPEG valide."


class InvalidImage(ValueError):
    """Fichier refusé ; le message est destiné à l'utilisateur."""


def has_allowed_extension(filename):
    """Retourne True si l'extension du fichier est autorisée."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _stream_size(stream):
    position = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(position)
    return size


def save_image(file_storage, folder):
    """Valide l'image envoyée et l'enregistre dans `folder`.

    Renvoie le nom du fichier créé (ex. « 3f2a….jpg ») ou lève InvalidImage.
    """
    if not has_allowed_extension(file_storage.filename or ""):
        raise InvalidImage(INVALID_TYPE)
    if _stream_size(file_storage.stream) > MAX_IMAGE_BYTES:
        raise InvalidImage("Image trop volumineuse (5 Mo maximum).")

    try:
        with Image.open(file_storage.stream) as source:
            extension = _FORMATS.get(source.format)
            if extension is None:
                raise InvalidImage(INVALID_CONTENT)
            if source.width * source.height > MAX_PIXELS:
                raise InvalidImage("Image trop grande (25 mégapixels maximum).")
            source.load()  # décode toute l'image : un fichier tronqué échoue ici
            # Copie orientée selon l'EXIF, avant de perdre les métadonnées.
            image = ImageOps.exif_transpose(source)
    except InvalidImage:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise InvalidImage(INVALID_CONTENT)

    if extension == "jpg" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    # Pillow recopie certaines métadonnées de image.info (EXIF, commentaires,
    # textes PNG) : on ne garde que la transparence.
    image.info = {k: v for k, v in image.info.items() if k == "transparency"}

    filename = f"{uuid.uuid4().hex}.{extension}"
    path = os.path.join(folder, filename)
    try:
        if extension == "jpg":
            image.save(path, "JPEG", quality=90)
        else:
            image.save(path, "PNG")
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return filename


def delete_image(filename, folder):
    """Supprime une image enregistrée par save_image() (ignore tout autre nom)."""
    if not filename or not STORED_NAME.match(filename):
        return
    try:
        os.remove(os.path.join(folder, filename))
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("Impossible de supprimer l'image %s", filename)
