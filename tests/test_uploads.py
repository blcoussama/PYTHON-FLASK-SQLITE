"""Images d'articles : contenu vérifié, taille limitée, fichiers nettoyés."""
import io
import os
import re

import pytest
from PIL import Image

from tests.conftest import article_id_from, create_article, csrf_token, image_bytes, register


def uploaded_files(app):
    return sorted(os.listdir(app.config["UPLOAD_FOLDER"]))


def image_name(db_rows, article_id):
    return db_rows("SELECT image_filename FROM articles WHERE id = ?", article_id)[0][0]


@pytest.fixture
def logged_in(client):
    register(client)
    return client


def test_image_valide_enregistree_sous_un_nom_aleatoire(app, logged_in, db_rows):
    article_id = article_id_from(create_article(logged_in, image=image_bytes("JPEG"),
                                                filename="Mes vacances (perso).jpg"))
    name = image_name(db_rows, article_id)
    assert re.fullmatch(r"[0-9a-f]{32}\.jpg", name)
    assert uploaded_files(app) == [name]

    served = logged_in.get(f"/uploads/{name}")
    assert served.status_code == 200
    assert served.mimetype == "image/jpeg"
    assert served.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("content, filename", [
    (b"<html><script>alert(1)</script></html>", "evil.jpg"),  # HTML déguisé
    (b"\x89PNG\r\n\x1a\n tronque", "tronque.png"),             # en-tête seul
    (image_bytes("GIF"), "anime.png"),                         # GIF renommé
    (image_bytes("PNG"), "image.gif"),                         # extension refusée
    (image_bytes("PNG"), "script.php"),
])
def test_fichier_refuse(app, logged_in, db_rows, content, filename):
    response = create_article(logged_in, image=content, filename=filename)
    assert response.status_code == 400
    assert uploaded_files(app) == []
    assert db_rows("SELECT COUNT(*) FROM articles")[0][0] == 0


def test_requete_trop_volumineuse_refusee(app, logged_in):
    too_big = b"0" * (app.config["MAX_CONTENT_LENGTH"] + 1)
    response = create_article(logged_in, image=too_big, filename="enorme.jpg")
    assert response.status_code == 413
    assert uploaded_files(app) == []


def test_metadonnees_exif_retirees(app, logged_in, db_rows):
    exif = Image.Exif()
    exif[0x010F] = "AppareilSecret"  # Make
    article_id = article_id_from(create_article(
        logged_in, image=image_bytes("JPEG", exif=exif.tobytes()), filename="photo.jpg"))
    path = os.path.join(app.config["UPLOAD_FOLDER"], image_name(db_rows, article_id))
    with open(path, "rb") as stored:
        assert b"AppareilSecret" not in stored.read()


def _edit(client, article_id, **extra):
    data = {"title": "Un article de test", "content": "Contenu de l'article de test.",
            "csrf_token": csrf_token(client)}
    data.update(extra)
    return client.post(f"/edit-article/{article_id}", data=data,
                       content_type="multipart/form-data")


def test_remplacer_retirer_et_supprimer_efface_les_fichiers(app, logged_in, db_rows):
    article_id = article_id_from(create_article(logged_in, image=image_bytes()))
    first = image_name(db_rows, article_id)

    assert _edit(logged_in, article_id,
                 image=(io.BytesIO(image_bytes("JPEG")), "nouvelle.jpg")).status_code == 302
    second = image_name(db_rows, article_id)
    assert second != first
    assert uploaded_files(app) == [second]  # l'ancienne image est effacée

    # Modification sans nouvelle image : l'image actuelle est conservée.
    assert _edit(logged_in, article_id).status_code == 302
    assert image_name(db_rows, article_id) == second

    # Bouton « Supprimer l'image »
    assert _edit(logged_in, article_id, remove_image="true").status_code == 302
    assert image_name(db_rows, article_id) is None
    assert uploaded_files(app) == []

    other_id = article_id_from(create_article(logged_in, image=image_bytes()))
    assert len(uploaded_files(app)) == 1
    logged_in.post(f"/delete-article/{other_id}", headers={"X-CSRFToken": csrf_token(logged_in)})
    assert uploaded_files(app) == []


def test_modification_refusee_ne_laisse_pas_de_fichier(app, logged_in, db_rows):
    article_id = article_id_from(create_article(logged_in))
    response = _edit(logged_in, article_id, title="abc",
                     image=(io.BytesIO(image_bytes()), "photo.png"))
    assert response.status_code == 200  # formulaire réaffiché avec l'erreur
    assert uploaded_files(app) == []


@pytest.mark.parametrize("path", ["/uploads/../test.db", "/uploads/..%2Ftest.db",
                                  "/uploads/inconnu.png", "/uploads/test.db"])
def test_route_uploads_ne_sert_que_les_images_generees(logged_in, path):
    assert logged_in.get(path).status_code == 404
