import pytest
from werkzeug.security import check_password_hash

from main import create_app
from tests.conftest import PASSWORD, csrf_token, login, register


def test_inscription_connecte_et_hache_le_mot_de_passe(client, db_rows):
    response = register(client)
    assert response.status_code == 302
    assert client.get("/my-articles").status_code == 200

    (stored,) = db_rows("SELECT password_hash FROM users WHERE username = 'alice'")[0]
    assert stored != PASSWORD
    assert stored.startswith(("scrypt:", "pbkdf2:"))  # empreinte salée Werkzeug
    assert check_password_hash(stored, PASSWORD)


def test_inscription_refuse_doublons_et_donnees_invalides(client, other_client):
    register(client)
    duplicate = register(other_client, username="alice", email="autre@example.com")
    assert "existe déjà" in duplicate.get_data(as_text=True)

    too_short = register(other_client, username="bruno", password="court")
    assert "au moins 8 caractères" in too_short.get_data(as_text=True)
    assert other_client.get("/my-articles").status_code == 302


def test_connexion_reussie_et_echouee(client, other_client):
    register(client)

    wrong = login(other_client, password="mauvais-mot-de-passe")
    assert wrong.status_code == 200
    assert "incorrect" in wrong.get_data(as_text=True)
    with other_client.session_transaction() as session:
        assert "user_id" not in session

    assert login(other_client).status_code == 302
    assert other_client.get("/my-articles").status_code == 200


def test_la_session_ne_contient_que_l_identifiant(client):
    register(client)
    with client.session_transaction() as session:
        assert set(session.keys()) <= {"user_id", "_permanent", "csrf_token"}
        assert isinstance(session["user_id"], int)


def test_deconnexion_en_post_uniquement(client):
    register(client)
    assert client.get("/logout").status_code == 405
    assert client.get("/my-articles").status_code == 200

    response = client.post("/logout", data={"csrf_token": csrf_token(client)})
    assert response.status_code == 302
    assert client.get("/my-articles").status_code == 302


def _session_cookie(response):
    return next(h for h in response.headers.getlist("Set-Cookie") if h.startswith("session="))


def test_cookie_de_session_httponly_samesite_secure(client):
    cookie = _session_cookie(register(client))
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" in cookie  # par défaut (hors mode debug)


def test_cookie_non_secure_en_debug_local(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "1")
    app = create_app({"SECRET_KEY": "x", "DATABASE_PATH": str(tmp_path / "d.db"),
                      "UPLOAD_FOLDER": str(tmp_path / "u")})
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_secret_key_obligatoire(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"DATABASE_PATH": str(tmp_path / "d.db"), "UPLOAD_FOLDER": str(tmp_path / "u")})


def test_debug_desactive_par_defaut(app):
    assert app.debug is False
