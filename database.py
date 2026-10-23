import os
import sqlite3
from contextlib import contextmanager

from werkzeug.security import check_password_hash, generate_password_hash

# Empreinte factice utilisée quand l'utilisateur n'existe pas : la vérification
# prend alors le même temps, ce qui évite de deviner les noms d'utilisateur
# existants en mesurant le temps de réponse.
_DUMMY_HASH = generate_password_hash("mot-de-passe-factice")

# Colonnes publiques d'un utilisateur : l'empreinte du mot de passe n'en fait
# jamais partie (elle ne doit quitter la base que pour être vérifiée).
_USER_COLUMNS = "id, username, email, created_at"

_ARTICLE_SELECT = '''
    SELECT a.*, u.username AS author_name,
           (SELECT COUNT(*) FROM likes WHERE article_id = a.id) AS likes_count,
           (SELECT COUNT(*) FROM comments WHERE article_id = a.id) AS comments_count
    FROM articles a
    JOIN users u ON a.author_id = u.id
'''


class Database:
    def __init__(self, db_path="data/blog.db"):
        self.db_path = db_path
        # Créer le dossier data s'il n'existe pas
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def get_connection(self):
        """Ouvre une connexion SQLite (lignes accessibles par nom de colonne)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connect(self):
        """Connexion validée en cas de succès, annulée en cas d'erreur, toujours fermée."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_database(self):
        """Initialize database with tables"""
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    content TEXT NOT NULL,
                    image_filename TEXT,
                    author_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (author_id) REFERENCES users (id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    article_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS likes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(article_id, user_id),
                    FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS saved_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(article_id, user_id),
                    FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                );
            ''')

    # ── Mots de passe ───────────────────────────────────────────────
    @staticmethod
    def hash_password(password):
        """Empreinte salée et lente (scrypt par défaut avec Werkzeug 3)."""
        return generate_password_hash(password)

    @staticmethod
    def verify_password(password, password_hash):
        """Vérifie un mot de passe en temps constant."""
        return check_password_hash(password_hash, password)

    # ── Utilisateurs ────────────────────────────────────────────────
    def create_user(self, username, email, password):
        """Crée un utilisateur et le renvoie (sans empreinte), ou None si doublon."""
        try:
            with self.connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, self.hash_password(password)),
                )
                user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return None
        return self.get_user_by_id(user_id)

    def get_user_by_credentials(self, username, password):
        """Renvoie l'utilisateur (sans empreinte) si les identifiants sont corrects."""
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT {_USER_COLUMNS}, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if row is None:
            self.verify_password(password, _DUMMY_HASH)
            return None
        if not self.verify_password(password, row["password_hash"]):
            return None

        user = dict(row)
        user.pop("password_hash")
        return user

    def _get_user_where(self, column, value):
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT {_USER_COLUMNS} FROM users WHERE {column} = ?", (value,)
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id):
        """Get user by ID"""
        return self._get_user_where("id", user_id)

    def get_user_by_username(self, username):
        """Get user by username"""
        return self._get_user_where("username", username)

    def get_user_by_email(self, email):
        """Get user by email"""
        return self._get_user_where("email", email)

    # ── Articles ────────────────────────────────────────────────────
    def create_article(self, title, description, content, image_filename, author_id):
        """Create a new article"""
        with self.connect() as conn:
            cursor = conn.execute(
                '''INSERT INTO articles (title, description, content, image_filename, author_id)
                   VALUES (?, ?, ?, ?, ?)''',
                (title, description, content, image_filename, author_id),
            )
            return cursor.lastrowid

    def get_article_by_id(self, article_id):
        """Get article by ID with author info"""
        with self.connect() as conn:
            row = conn.execute(_ARTICLE_SELECT + " WHERE a.id = ?", (article_id,)).fetchone()
        return dict(row) if row else None

    def get_all_articles(self, limit=50):
        """Articles les plus récents (50 au maximum)."""
        with self.connect() as conn:
            rows = conn.execute(
                _ARTICLE_SELECT + " ORDER BY a.created_at DESC, a.id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user_articles(self, user_id):
        """Get articles by user"""
        with self.connect() as conn:
            rows = conn.execute(
                _ARTICLE_SELECT + " WHERE a.author_id = ? ORDER BY a.created_at DESC, a.id DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_article(self, article_id, title, description, content, image_filename):
        """Update an article"""
        with self.connect() as conn:
            cursor = conn.execute(
                '''UPDATE articles
                   SET title = ?, description = ?, content = ?, image_filename = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?''',
                (title, description, content, image_filename, article_id),
            )
            return cursor.rowcount > 0

    def delete_article(self, article_id, user_id):
        """Supprime un article (seulement par son auteur) ; commentaires, likes et
        sauvegardes suivent grâce à ON DELETE CASCADE."""
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM articles WHERE id = ? AND author_id = ?", (article_id, user_id)
            )
            return cursor.rowcount > 0

    # ── Commentaires ────────────────────────────────────────────────
    def add_comment(self, article_id, user_id, content):
        """Add a comment to an article"""
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO comments (article_id, user_id, content) VALUES (?, ?, ?)",
                (article_id, user_id, content),
            )
            return cursor.lastrowid

    def get_article_comments(self, article_id):
        """Get comments for an article"""
        with self.connect() as conn:
            rows = conn.execute(
                '''SELECT c.*, u.username AS author_name
                   FROM comments c
                   JOIN users u ON c.user_id = u.id
                   WHERE c.article_id = ?
                   ORDER BY c.created_at DESC, c.id DESC''',
                (article_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Likes et sauvegardes ────────────────────────────────────────
    def _toggle(self, table, article_id, user_id):
        """Ajoute ou retire la ligne (article, utilisateur) ; renvoie True si ajoutée."""
        with self.connect() as conn:
            deleted = conn.execute(
                f"DELETE FROM {table} WHERE article_id = ? AND user_id = ?",
                (article_id, user_id),
            ).rowcount
            if not deleted:
                conn.execute(
                    f"INSERT INTO {table} (article_id, user_id) VALUES (?, ?)",
                    (article_id, user_id),
                )
            return not deleted

    def _exists(self, table, article_id, user_id):
        if not user_id:
            return False
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE article_id = ? AND user_id = ?",
                (article_id, user_id),
            ).fetchone()
        return row is not None

    def toggle_like(self, article_id, user_id):
        """Toggle like for an article"""
        liked = self._toggle("likes", article_id, user_id)
        with self.connect() as conn:
            likes_count = conn.execute(
                "SELECT COUNT(*) FROM likes WHERE article_id = ?", (article_id,)
            ).fetchone()[0]
        return {'liked': liked, 'likes_count': likes_count}

    def is_article_liked(self, article_id, user_id):
        """Check if article is liked by user"""
        return self._exists("likes", article_id, user_id)

    def get_liked_articles(self, user_id):
        """Get articles liked by user"""
        with self.connect() as conn:
            rows = conn.execute(
                _ARTICLE_SELECT
                + " JOIN likes l ON a.id = l.article_id WHERE l.user_id = ?"
                  " ORDER BY l.created_at DESC, l.id DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def toggle_save(self, article_id, user_id):
        """Toggle save for an article"""
        return {'saved': self._toggle("saved_articles", article_id, user_id)}

    def is_article_saved(self, article_id, user_id):
        """Check if article is saved by user"""
        return self._exists("saved_articles", article_id, user_id)

    def get_saved_articles(self, user_id):
        """Get articles saved by user"""
        with self.connect() as conn:
            rows = conn.execute(
                _ARTICLE_SELECT
                + " JOIN saved_articles s ON a.id = s.article_id WHERE s.user_id = ?"
                  " ORDER BY s.created_at DESC, s.id DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]
