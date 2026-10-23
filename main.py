import os
from datetime import datetime, timedelta
from types import SimpleNamespace

from flask import (
    Blueprint, Flask, abort, current_app, g, jsonify, redirect,
    render_template, request, send_from_directory, session, url_for
)
from flask_wtf.csrf import CSRFError, CSRFProtect

from database import Database
from handlers.article_handler import ArticleHandler
from handlers.auth_handler import AuthHandler
from utils.uploads import STORED_NAME, InvalidImage, delete_image, save_image

bp = Blueprint("blog", __name__)
csrf = CSRFProtect()

# Routes appelées en fetch() par le JavaScript : leurs erreurs sont en JSON.
JSON_ENDPOINTS = {
    "blog.delete_article", "blog.like_article",
    "blog.save_article", "blog.comment_article",
}


def _env_flag(name, default=False):
    """Lit une variable d'environnement booléenne (1/true/yes/on)."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(test_config=None):
    """Fabrique de l'application : la configuration vient de l'environnement."""
    app = Flask(__name__, template_folder="templates")

    debug = _env_flag("FLASK_DEBUG")
    app.config.from_mapping(
        # Clé de signature des cookies de session : obligatoire, jamais en dur.
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DATABASE_PATH=os.environ.get(
            "DATABASE_PATH", os.path.join(app.root_path, "data", "blog.db")
        ),
        # Images envoyées : hors de static/, servies par la route /uploads/.
        UPLOAD_FOLDER=os.environ.get(
            "UPLOAD_FOLDER", os.path.join(app.root_path, "data", "uploads")
        ),
        # Taille maximale d'une requête : image de 5 Mo + champs texte.
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        # Cookie de session : inaccessible au JavaScript, non envoyé par les
        # requêtes intersites (sauf navigation GET), HTTPS uniquement hors debug.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_env_flag("SESSION_COOKIE_SECURE", default=not debug),
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),  # Sessions valides 7 jours
    )
    if test_config:
        app.config.update(test_config)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY manquante : définissez la variable d'environnement SECRET_KEY "
            "(par exemple avec python -c \"import secrets; print(secrets.token_hex(32))\")."
        )

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db = Database(app.config["DATABASE_PATH"])
    db.init_database()
    app.extensions["blog"] = SimpleNamespace(
        db=db,
        auth=AuthHandler(db),
        articles=ArticleHandler(db),
    )

    # Jeton CSRF exigé sur toutes les requêtes POST (champ caché csrf_token des
    # formulaires, en-tête X-CSRFToken pour les appels fetch()).
    csrf.init_app(app)

    app.add_template_filter(format_date_filter, "format_date")
    app.add_template_filter(truncate_filter, "truncate")
    app.add_template_global(upload_url, "upload_url")
    app.after_request(set_security_headers)
    app.register_blueprint(bp)
    register_error_handlers(app)
    return app


def register_error_handlers(app):
    def error_response(code, message):
        if request.endpoint in JSON_ENDPOINTS:
            return jsonify(success=False, error=message), code
        return render_template(
            "error.html", title=f"Erreur {code} - Blog Platform",
            user=get_current_user(), code=code, message=message,
        ), code

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return error_response(
            400, "Jeton de sécurité (CSRF) manquant ou expiré : rechargez la page et réessayez."
        )

    @app.errorhandler(403)
    def forbidden(error):
        return error_response(403, "Vous n'avez pas le droit d'effectuer cette action.")

    @app.errorhandler(404)
    def not_found(error):
        return error_response(404, "Page introuvable.")

    @app.errorhandler(413)
    def too_large(error):
        return error_response(413, "Fichier trop volumineux (5 Mo maximum).")


def set_security_headers(response):
    # Le navigateur ne doit jamais « deviner » un type différent de celui
    # annoncé, ni afficher le site dans un cadre d'un autre site.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


def services():
    return current_app.extensions["blog"]


def upload_url(filename):
    """URL d'une image d'article (utilisable dans les templates)."""
    return url_for("blog.uploaded_file", filename=filename)


def upload_folder():
    return current_app.config["UPLOAD_FOLDER"]


# ── Filtres de Template ─────────────────────────────────────────────
MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre")


def format_date_filter(date_value):
    """Formate la date pour l'affichage dans les templates"""
    if isinstance(date_value, str):
        # Si c'est une chaîne, essayer de l'analyser
        try:
            date_value = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
        except ValueError:
            try:
                # Essayer différents formats courants
                date_value = datetime.strptime(date_value, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return date_value  # Retourner tel quel si impossible à analyser

    if isinstance(date_value, datetime):
        # Mois en français sans dépendre de la locale du serveur
        month = MONTHS_FR[date_value.month - 1]
        return f"{date_value.day:02d} {month} {date_value.year} à {date_value:%H:%M}"

    return str(date_value)  # Solution de secours vers représentation string


def truncate_filter(text, length=100):
    """Tronque le texte à la longueur spécifiée et ajoute des points de suspension si nécessaire"""
    if not text:
        return ""

    text = str(text)
    if len(text) <= length:
        return text

    return text[:length].rstrip() + "..."


# ── Fonctions d'aide ────────────────────────────────────────────────
def get_current_user():
    """Utilisateur connecté, relu en base à partir de l'identifiant stocké dans
    la session signée (aucune autre donnée utilisateur n'est mise en session)."""
    if "current_user" not in g:
        user_id = session.get("user_id")
        user = services().db.get_user_by_id(user_id) if user_id else None
        if user_id and user is None:
            session.clear()  # compte supprimé : on invalide la session
        g.current_user = user
    return g.current_user


def start_session(user):
    """Ouvre une session neuve (évite la fixation de session)."""
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True


# ── Routes ──────────────────────────────────────────────────────────
@bp.route("/")
def home():
    user = get_current_user()
    articles = services().db.get_all_articles()
    return render_template(
        "index.html",
        title="Accueil - Blog Platform",
        user=user,
        articles=articles
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    user = get_current_user()
    if user:
        return redirect(url_for("blog.home"))

    if request.method == "POST":
        result = services().auth.login(request.form)
        if result["success"]:
            start_session(result["user"])
            return redirect(url_for("blog.home"))
        return render_template(
            "auth/login.html",
            title="Connexion - Blog Platform",
            error=result["error"]
        )

    return render_template("auth/login.html", title="Connexion - Blog Platform")


@bp.route("/register", methods=["GET", "POST"])
def register():
    user = get_current_user()
    if user:
        return redirect(url_for("blog.home"))

    if request.method == "POST":
        result = services().auth.register(request.form)
        if result["success"]:
            start_session(result["user"])
            return redirect(url_for("blog.home"))
        return render_template(
            "auth/register.html",
            title="Inscription - Blog Platform",
            error=result["error"]
        )

    return render_template("auth/register.html", title="Inscription - Blog Platform")


@bp.route("/logout", methods=["POST"])
def logout():
    # POST uniquement : un simple lien ou une image ne peut plus déconnecter.
    session.clear()
    return redirect(url_for("blog.home"))


@bp.route("/create-article", methods=["GET", "POST"])
def create_article():
    user = get_current_user()
    if not user:
        return redirect(url_for("blog.login"))

    if request.method == "POST":
        # 1) Récupérer les champs texte
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        content = request.form.get("content", "").strip()

        # 2) Récupérer et valider l’image uploadée (contenu vérifié par Pillow)
        image_file = request.files.get("image")
        saved_filename = None

        if image_file and image_file.filename:
            try:
                saved_filename = save_image(image_file, upload_folder())
            except InvalidImage as error:
                return render_template(
                    "articles/create.html",
                    title="Créer un article - Blog Platform",
                    user=user,
                    error=str(error)
                ), 400

        # 3) Appeler la méthode ArticleHandler (ajustée pour ces nouveaux paramètres)
        result = services().articles.create_article(
            title=title,
            description=description,
            content=content,
            image_filename=saved_filename,
            user_id=user["id"]
        )

        if result["success"]:
            return redirect(url_for("blog.article_detail", article_id=result["article_id"]))
        else:
            delete_image(saved_filename, upload_folder())  # article non créé
            return render_template(
                "articles/create.html",
                title="Créer un article - Blog Platform",
                user=user,
                error=result["error"]
            )

    # Si c’est une requête GET → afficher le formulaire vierge
    return render_template(
        "articles/create.html",
        title="Créer un article - Blog Platform",
        user=user
    )


@bp.route("/article/<int:article_id>")
def article_detail(article_id):
    user = get_current_user()
    db = services().db
    article = db.get_article_by_id(article_id) or abort(404)
    comments = db.get_article_comments(article_id)
    is_liked = db.is_article_liked(article_id, user["id"]) if user else False
    is_saved = db.is_article_saved(article_id, user["id"]) if user else False

    return render_template(
        "articles/detail.html",
        title=f"{article['title']} - Blog Platform",
        user=user,
        article=article,
        comments=comments,
        is_liked=is_liked,
        is_saved=is_saved
    )


@bp.route("/edit-article/<int:article_id>", methods=["GET", "POST"])
def edit_article(article_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("blog.login"))

    # 1) On récupère l'article existant (avec ses champs actuels : title, description, image_filename, etc.)
    article = services().db.get_article_by_id(article_id) or abort(404)
    if article["author_id"] != user["id"]:
        abort(403)

    if request.method == "POST":
        # 2) Récupérer les nouveaux champs texte
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        content = request.form.get("content", "").strip()

        # 3) Image : nouvelle image, suppression demandée, ou image actuelle
        old_filename = article.get("image_filename")
        image_file = request.files.get("image")
        new_filename = None

        # Si l’utilisateur a choisi une nouvelle image…
        if image_file and image_file.filename:
            try:
                new_filename = save_image(image_file, upload_folder())
            except InvalidImage as error:
                return render_template(
                    "articles/edit.html",
                    title=f"Modifier {article['title']} - Blog Platform",
                    user=user,
                    article=article,
                    error=str(error)
                ), 400

        if new_filename:
            saved_filename = new_filename
        elif request.form.get("remove_image") == "true":
            # Bouton « Supprimer l'image » du formulaire
            saved_filename = None
        else:
            saved_filename = old_filename

        # 4) Appeler la méthode ArticleHandler.edit_article(...) mise à jour
        result = services().articles.edit_article(
            article_id=article_id,
            title=title,
            description=description,
            content=content,
            image_filename=saved_filename,
            user_id=user["id"]
        )

        if result["success"]:
            # L'ancienne image remplacée ou retirée ne reste pas sur le disque.
            if old_filename and old_filename != saved_filename:
                delete_image(old_filename, upload_folder())
            return redirect(url_for("blog.article_detail", article_id=article_id))
        else:
            delete_image(new_filename, upload_folder())  # modification refusée
            return render_template(
                "articles/edit.html",
                title=f"Modifier {article['title']} - Blog Platform",
                user=user,
                article=article,
                error=result["error"]
            )

    # Si GET → on affiche le formulaire prérempli
    return render_template(
        "articles/edit.html",
        title=f"Modifier {article['title']} - Blog Platform",
        user=user,
        article=article
    )


@bp.route("/delete-article/<int:article_id>", methods=["POST"])
def delete_article(article_id):
    user = get_current_user()
    if not user:
        return jsonify(success=False, error="Non authentifié"), 401

    article = services().db.get_article_by_id(article_id)
    result = services().articles.delete_article(article_id, user["id"])
    if result["success"] and article:
        delete_image(article.get("image_filename"), upload_folder())
    return jsonify(result), (200 if result["success"] else 403)


@bp.route("/like-article/<int:article_id>", methods=["POST"])
def like_article(article_id):
    user = get_current_user()
    if not user:
        return jsonify(success=False, error="Non authentifié"), 401
    result = services().articles.toggle_like(article_id, user["id"])
    return jsonify(result), (200 if result["success"] else 404)


@bp.route("/save-article/<int:article_id>", methods=["POST"])
def save_article(article_id):
    user = get_current_user()
    if not user:
        return jsonify(success=False, error="Non authentifié"), 401
    result = services().articles.toggle_save(article_id, user["id"])
    return jsonify(result), (200 if result["success"] else 404)


@bp.route("/comment-article/<int:article_id>", methods=["POST"])
def comment_article(article_id):
    user = get_current_user()
    if not user:
        return jsonify(success=False, error="Non authentifié"), 401
    result = services().articles.add_comment(article_id, request.form, user["id"])
    return jsonify(result), (200 if result["success"] else 400)


@bp.route("/uploads/<filename>")
def uploaded_file(filename):
    # Seuls les noms générés par save_image() sont servis.
    if not STORED_NAME.match(filename):
        abort(404)
    return send_from_directory(upload_folder(), filename)


@bp.route("/my-articles")
def my_articles():
    user = get_current_user()
    if not user:
        return redirect(url_for("blog.login"))
    articles = services().db.get_user_articles(user["id"])
    return render_template(
        "user/my_articles.html",
        title="Mes articles - Blog Platform",
        user=user,
        articles=articles
    )


@bp.route("/liked-articles")
def liked_articles():
    user = get_current_user()
    if not user:
        return redirect(url_for("blog.login"))
    articles = services().db.get_liked_articles(user["id"])
    return render_template(
        "user/liked_articles.html",
        title="Articles aimés - Blog Platform",
        user=user,
        articles=articles
    )


@bp.route("/saved-articles")
def saved_articles():
    user = get_current_user()
    if not user:
        return redirect(url_for("blog.login"))
    articles = services().db.get_saved_articles(user["id"])
    return render_template(
        "user/saved_articles.html",
        title="Articles sauvegardés - Blog Platform",
        user=user,
        articles=articles
    )


# ── Exécution ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        from dotenv import load_dotenv  # lit un fichier .env local s'il existe
        load_dotenv()
    except ImportError:
        pass
    # Mode debug uniquement si FLASK_DEBUG=1 (jamais en production : la console
    # de débogage Werkzeug permet d'exécuter du code sur le serveur).
    create_app().run(
        debug=_env_flag("FLASK_DEBUG"),
        port=int(os.environ.get("PORT", "8000")),
    )
