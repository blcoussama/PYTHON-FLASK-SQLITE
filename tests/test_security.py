"""Tests d'attaque : CSRF, traversée de chemin par cookie, sessions forgées."""
import json

import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface

from tests.conftest import article_id_from, create_article, csrf_token, register

# Les 9 routes POST de l'application.
POST_ROUTES = [
    "/login", "/register", "/logout", "/create-article", "/edit-article/{id}",
    "/delete-article/{id}", "/like-article/{id}", "/save-article/{id}", "/comment-article/{id}",
]


@pytest.mark.parametrize("route", POST_ROUTES)
@pytest.mark.parametrize("token", [None, "jeton-invalide"])
def test_post_sans_jeton_csrf_valide_refuse(client, db_rows, route, token):
    register(client)
    article_id = article_id_from(create_article(client, title="Article cible"))

    data = {"title": "Modifié par un site tiers", "content": "Contenu injecté depuis un autre site.",
            "username": "x", "password": "y"}
    if token:
        data["csrf_token"] = token
    response = client.post(route.format(id=article_id), data=data)

    assert response.status_code == 400
    assert db_rows("SELECT title FROM articles") == [("Article cible",)]
    assert db_rows("SELECT COUNT(*) FROM comments")[0][0] == 0
    assert db_rows("SELECT COUNT(*) FROM likes")[0][0] == 0
    assert client.get("/my-articles").status_code == 200  # toujours connecté


def test_routes_fetch_renvoient_une_erreur_json(client):
    register(client)
    response = client.post("/like-article/1")
    assert response.status_code == 400
    assert response.json["success"] is False


def test_ancien_cookie_session_id_avec_traversee_ignore(app, client, tmp_path, monkeypatch):
    """Avant : session_id=../../forged faisait lire data/sessions/../../forged.json."""
    monkeypatch.chdir(tmp_path)
    forged = {"user": {"id": 1, "username": "pirate"}, "expires_at": "2099-01-01T00:00:00"}
    (tmp_path / "forged.json").write_text(json.dumps(forged))
    (tmp_path / "victim.json").write_text("{}")
    register(client)  # crée l'utilisateur 1, puis on repart d'un navigateur vierge

    attacker = app.test_client()
    attacker.set_cookie("session_id", "../../forged")
    assert attacker.get("/my-articles").status_code == 302  # non connecté

    attacker.set_cookie("session_id", "../../victim")
    attacker.post("/logout", data={"csrf_token": csrf_token(attacker)})
    assert (tmp_path / "victim.json").exists()


def _session_cookie_signed_with(secret, payload):
    other = Flask("autre")
    other.secret_key = secret
    return SecureCookieSessionInterface().get_signing_serializer(other).dumps(payload)


def test_cookie_de_session_signe_avec_une_autre_cle_refuse(app, client):
    register(client)  # utilisateur 1
    attacker = app.test_client()
    attacker.set_cookie("session", _session_cookie_signed_with("cle-devinee", {"user_id": 1}))
    assert attacker.get("/my-articles").status_code == 302


def test_cookie_de_session_modifie_refuse(app, client):
    register(client)
    attacker = app.test_client()
    attacker.set_cookie("session", "eyJ1c2VyX2lkIjoxfQ.ZZZZZZ.signature-invalide")
    assert attacker.get("/my-articles").status_code == 302


def test_session_d_un_compte_supprime_invalidee(app, client, db_rows):
    register(client)
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    assert client.get("/my-articles").status_code == 302


def test_en_tetes_de_securite(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
