"""Fixtures communes : application isolée (base et images dans un dossier
temporaire) et petits utilitaires qui passent par les vrais formulaires,
jeton CSRF compris."""
import io
import re
import sqlite3

import pytest
from PIL import Image

from main import create_app

PASSWORD = "motdepasse-test"


@pytest.fixture
def app(tmp_path, monkeypatch):
    for name in ("FLASK_DEBUG", "SESSION_COOKIE_SECURE", "DATABASE_PATH", "UPLOAD_FOLDER"):
        monkeypatch.delenv(name, raising=False)
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "cle-de-test-uniquement",
        "DATABASE_PATH": str(tmp_path / "test.db"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def other_client(app):
    """Second navigateur, pour un deuxième utilisateur."""
    return app.test_client()


@pytest.fixture
def db_rows(app):
    def query(sql, *params):
        conn = sqlite3.connect(app.config["DATABASE_PATH"])
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    return query


def csrf_token(client):
    """Jeton CSRF lu dans la balise <meta> de la page d'accueil."""
    html = client.get("/").get_data(as_text=True)
    return re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)


def register(client, username="alice", email=None, password=PASSWORD):
    return client.post("/register", data={
        "username": username,
        "email": email or f"{username}@example.com",
        "password": password,
        "confirm_password": password,
        "csrf_token": csrf_token(client),
    })


def login(client, username="alice", password=PASSWORD):
    return client.post("/login", data={
        "username": username, "password": password, "csrf_token": csrf_token(client),
    })


def image_bytes(fmt="PNG", size=(40, 30), **save_options):
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(buffer, fmt, **save_options)
    return buffer.getvalue()


def create_article(client, title="Un article de test", content="Contenu de l'article de test.",
                   image=None, filename="photo.png"):
    """Crée un article ; renvoie la réponse (redirection vers /article/<id> si succès)."""
    data = {"title": title, "description": "Description", "content": content,
            "csrf_token": csrf_token(client)}
    if image is not None:
        data["image"] = (io.BytesIO(image), filename)
    return client.post("/create-article", data=data, content_type="multipart/form-data")


def article_id_from(response):
    match = re.search(r"/article/(\d+)$", response.headers.get("Location", ""))
    assert match, f"pas de redirection vers un article : {response.status_code}"
    return int(match.group(1))
