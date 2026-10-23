from tests.conftest import article_id_from, create_article, csrf_token, register


def test_crud_de_ses_propres_articles(client):
    register(client)
    article_id = article_id_from(create_article(client, title="Premier article"))

    page = client.get(f"/article/{article_id}").get_data(as_text=True)
    assert "Premier article" in page
    assert "Premier article" in client.get("/").get_data(as_text=True)

    edited = client.post(f"/edit-article/{article_id}", data={
        "title": "Titre modifié", "description": "", "content": "Nouveau contenu assez long.",
        "csrf_token": csrf_token(client),
    }, content_type="multipart/form-data")
    assert edited.status_code == 302
    assert "Titre modifié" in client.get(f"/article/{article_id}").get_data(as_text=True)

    deleted = client.post(f"/delete-article/{article_id}",
                          headers={"X-CSRFToken": csrf_token(client)})
    assert deleted.status_code == 200 and deleted.json["success"] is True
    assert client.get(f"/article/{article_id}").status_code == 404


def test_validation_des_articles(client):
    register(client)
    response = create_article(client, title="abc")
    assert response.status_code == 200
    assert "au moins 5 caractères" in response.get_data(as_text=True)


def test_un_autre_utilisateur_ne_peut_ni_modifier_ni_supprimer(client, other_client, db_rows):
    register(client, "alice")
    article_id = article_id_from(create_article(client, title="Article d'Alice"))
    register(other_client, "bruno")

    assert other_client.get(f"/edit-article/{article_id}").status_code == 403
    edit = other_client.post(f"/edit-article/{article_id}", data={
        "title": "Piraté par Bruno", "content": "Contenu remplacé par Bruno.",
        "csrf_token": csrf_token(other_client),
    }, content_type="multipart/form-data")
    assert edit.status_code == 403

    delete = other_client.post(f"/delete-article/{article_id}",
                               headers={"X-CSRFToken": csrf_token(other_client)})
    assert delete.status_code == 403
    assert delete.json["success"] is False

    assert db_rows("SELECT title FROM articles WHERE id = ?", article_id) == [("Article d'Alice",)]


def test_visiteur_anonyme(client):
    assert client.get("/create-article").status_code == 302
    assert client.get("/my-articles").status_code == 302
    like = client.post("/like-article/1", headers={"X-CSRFToken": csrf_token(client)})
    assert like.status_code == 401


def test_likes_sauvegardes_et_commentaires(client, other_client):
    register(client, "alice")
    article_id = article_id_from(create_article(client))
    register(other_client, "bruno")
    headers = {"X-CSRFToken": csrf_token(other_client)}

    like = other_client.post(f"/like-article/{article_id}", headers=headers)
    assert like.json == {"success": True, "liked": True, "likes_count": 1}
    save = other_client.post(f"/save-article/{article_id}", headers=headers)
    assert save.json == {"success": True, "saved": True}
    assert "Un article de test" in other_client.get("/liked-articles").get_data(as_text=True)
    assert "Un article de test" in other_client.get("/saved-articles").get_data(as_text=True)

    unlike = other_client.post(f"/like-article/{article_id}", headers=headers)
    assert unlike.json["liked"] is False and unlike.json["likes_count"] == 0

    comment = other_client.post(f"/comment-article/{article_id}", headers=headers,
                                data={"content": "Très bon article"})
    assert comment.json["success"] is True and comment.json["comments_count"] == 1
    empty = other_client.post(f"/comment-article/{article_id}", headers=headers,
                              data={"content": "   "})
    assert empty.status_code == 400

    missing = other_client.post("/like-article/9999", headers=headers)
    assert missing.status_code == 404


def test_supprimer_un_article_supprime_commentaires_likes_et_sauvegardes(client, db_rows):
    register(client)
    article_id = article_id_from(create_article(client))
    headers = {"X-CSRFToken": csrf_token(client)}
    client.post(f"/like-article/{article_id}", headers=headers)
    client.post(f"/save-article/{article_id}", headers=headers)
    client.post(f"/comment-article/{article_id}", headers=headers, data={"content": "Bonjour"})

    client.post(f"/delete-article/{article_id}", headers=headers)
    for table in ("comments", "likes", "saved_articles"):
        assert db_rows(f"SELECT COUNT(*) FROM {table}")[0][0] == 0, table


def test_le_html_des_articles_est_echappe(client):
    register(client)
    article_id = article_id_from(create_article(client, content="<script>alert(1)</script> texte"))
    page = client.get(f"/article/{article_id}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_dates_affichees_en_francais():
    from main import format_date_filter
    assert format_date_filter("2026-08-03 14:05:00") == "03 août 2026 à 14:05"
