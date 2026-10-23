"""Remplit la base avec des données de démonstration entièrement factices.

    python scripts/seed_demo.py --reset

Crée trois comptes (adresses @example.com, domaine réservé aux exemples),
quelques articles illustrés par des images générées ici même avec Pillow,
des commentaires, des likes et des sauvegardes. Le mot de passe des comptes
de démo vaut DEMO_PASSWORD (variable d'environnement) ou « demo1234 ».

Les chemins suivent ceux de l'application : DATABASE_PATH et UPLOAD_FOLDER,
par défaut data/blog.db et data/uploads.
"""
import argparse
import io
import os
import sys
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont
from werkzeug.datastructures import FileStorage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from database import Database  # noqa: E402
from utils.uploads import STORED_NAME, save_image  # noqa: E402

USERS = [
    ("alice_demo", "alice@example.com"),
    ("bruno_demo", "bruno@example.com"),
    ("chloe_demo", "chloe@example.com"),
]

ARTICLES = [
    {
        "author": "alice_demo",
        "title": "Activer les clés étrangères dans SQLite",
        "description": "Pourquoi ON DELETE CASCADE ne fait rien tant que PRAGMA foreign_keys est désactivé.",
        "content": (
            "SQLite accepte les contraintes FOREIGN KEY dans un CREATE TABLE, mais ne les "
            "applique que si la connexion exécute PRAGMA foreign_keys = ON. Sans cette ligne, "
            "supprimer un article laisse ses commentaires et ses likes orphelins.\n\n"
            "Dans ce blog, la méthode get_connection() active le pragma à chaque connexion : "
            "la suppression d'un article entraîne celle de ses commentaires, likes et sauvegardes."
        ),
        "cover": "SQLite",
        "colors": ((32, 76, 140), (88, 160, 220)),
        "days_ago": 9,
    },
    {
        "author": "bruno_demo",
        "title": "Hacher un mot de passe avec Werkzeug",
        "description": "generate_password_hash et check_password_hash plutôt qu'un SHA-256 sans sel.",
        "content": (
            "Un SHA-256 sans sel se calcule en quelques nanosecondes : deux utilisateurs ayant le "
            "même mot de passe ont la même empreinte et les tables précalculées la retrouvent vite.\n\n"
            "Werkzeug fournit generate_password_hash, qui utilise scrypt avec un sel aléatoire, et "
            "check_password_hash, qui compare en temps constant. Deux appels suffisent."
        ),
        "cover": "Werkzeug",
        "colors": ((120, 40, 90), (220, 110, 150)),
        "days_ago": 7,
    },
    {
        "author": "chloe_demo",
        "title": "Protéger ses formulaires Flask contre le CSRF",
        "description": "Flask-WTF, un champ caché et un en-tête pour les appels fetch().",
        "content": (
            "Une requête POST envoyée depuis un autre site part avec les cookies de l'utilisateur. "
            "Sans jeton CSRF, ce site peut publier ou supprimer un article à sa place.\n\n"
            "CSRFProtect vérifie un jeton sur chaque POST : un champ caché csrf_token dans les "
            "formulaires HTML et l'en-tête X-CSRFToken pour les appels JavaScript."
        ),
        "cover": "CSRF",
        "colors": ((30, 110, 80), (120, 200, 150)),
        "days_ago": 5,
    },
    {
        "author": "alice_demo",
        "title": "Vérifier une image envoyée avec Pillow",
        "description": "L'extension .jpg ne prouve rien : on ouvre le fichier et on le ré-encode.",
        "content": (
            "Un fichier nommé photo.jpg peut contenir du HTML. Avant d'enregistrer une image, "
            "l'application l'ouvre avec Pillow, vérifie qu'il s'agit d'un PNG ou d'un JPEG, limite "
            "sa taille, puis la ré-encode sous un nom aléatoire : les métadonnées EXIF disparaissent."
        ),
        "cover": "Pillow",
        "colors": ((150, 90, 20), (240, 180, 80)),
        "days_ago": 3,
    },
    {
        "author": "bruno_demo",
        "title": "Des sessions signées plutôt que des fichiers JSON",
        "description": "flask.session ne stocke que l'identifiant de l'utilisateur, dans un cookie signé.",
        "content": (
            "Construire un chemin de fichier à partir d'un cookie expose à la traversée de "
            "répertoires (../../). La session Flask est un cookie signé avec SECRET_KEY : il ne "
            "peut pas être modifié sans la clé, et il ne contient ici que l'identifiant du compte."
        ),
        "cover": "flask.session",
        "colors": ((70, 60, 140), (150, 140, 230)),
        "days_ago": 1,
    },
]

COMMENTS = [
    (0, "bruno_demo", "Je ne savais pas que le pragma était désactivé par défaut, merci !"),
    (0, "chloe_demo", "Bon rappel, j'avais des commentaires orphelins dans un autre projet."),
    (1, "alice_demo", "Et check_password_hash compare en temps constant, c'est un plus."),
    (2, "bruno_demo", "Le jeton dans une balise meta, c'est pratique pour fetch()."),
    (3, "chloe_demo", "Le ré-encodage retire aussi la position GPS des photos, bien vu."),
    (4, "alice_demo", "Plus de dossier data/sessions à nettoyer, c'est plus simple."),
]

LIKES = [(0, "bruno_demo"), (0, "chloe_demo"), (1, "alice_demo"), (2, "alice_demo"),
         (2, "bruno_demo"), (3, "chloe_demo"), (4, "alice_demo"), (4, "chloe_demo")]
SAVES = [(0, "chloe_demo"), (2, "alice_demo"), (3, "bruno_demo"), (4, "chloe_demo")]


def make_cover(label, colors):
    """Image de couverture générée (dégradé + mot-clé en ASCII), au format PNG."""
    width, height = 1200, 630
    top, bottom = colors
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / (height - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)

    # Police intégrée à Pillow (sans accents) : le texte reste en ASCII.
    font = ImageFont.load_default(size=130)
    small = ImageFont.load_default(size=40)
    draw.text((width // 2, height // 2 - 20), label, font=font, fill=(255, 255, 255), anchor="mm")
    draw.text((width // 2, height // 2 + 100), "Blog Flask - demo", font=small,
              fill=(255, 255, 255), anchor="mm")

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    return FileStorage(buffer, filename="cover.png", content_type="image/png")


def reset(db_path, upload_folder):
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.isdir(upload_folder):
        for name in os.listdir(upload_folder):
            if STORED_NAME.match(name):
                os.remove(os.path.join(upload_folder, name))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true",
                        help="supprime la base et les images existantes avant de remplir")
    args = parser.parse_args()

    db_path = os.environ.get("DATABASE_PATH", os.path.join(ROOT, "data", "blog.db"))
    upload_folder = os.environ.get("UPLOAD_FOLDER", os.path.join(ROOT, "data", "uploads"))
    password = os.environ.get("DEMO_PASSWORD", "demo1234")

    if args.reset:
        reset(db_path, upload_folder)
    os.makedirs(upload_folder, exist_ok=True)

    db = Database(db_path)
    db.init_database()
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            sys.exit("La base contient déjà des comptes : relancez avec --reset.")

    users = {}
    for username, email in USERS:
        users[username] = db.create_user(username, email, password)["id"]

    article_ids = []
    now = datetime.now()
    for article in ARTICLES:
        image = save_image(make_cover(article["cover"], article["colors"]), upload_folder)
        article_id = db.create_article(
            title=article["title"],
            description=article["description"],
            content=article["content"],
            image_filename=image,
            author_id=users[article["author"]],
        )
        created = (now - timedelta(days=article["days_ago"])).strftime("%Y-%m-%d %H:%M:%S")
        with db.connect() as conn:
            conn.execute("UPDATE articles SET created_at = ?, updated_at = ? WHERE id = ?",
                         (created, created, article_id))
        article_ids.append(article_id)

    for index, username, content in COMMENTS:
        db.add_comment(article_ids[index], users[username], content)
    for index, username in LIKES:
        db.toggle_like(article_ids[index], users[username])
    for index, username in SAVES:
        db.toggle_save(article_ids[index], users[username])

    print(f"Base de démo prête : {db_path}")
    print(f"{len(USERS)} comptes ({', '.join(u for u, _ in USERS)}), "
          f"{len(ARTICLES)} articles, {len(COMMENTS)} commentaires.")
    print("Mot de passe des comptes : valeur de DEMO_PASSWORD (par défaut demo1234).")


if __name__ == "__main__":
    main()
