import logging

logger = logging.getLogger(__name__)


class ArticleHandler:
    def __init__(self, database):
        self.db = database

    def create_article(self, title, description, content, image_filename, user_id):
        """
        Create a new article avec les champs :
          - title (str)
          - description (str ou "")
          - content (str)
          - image_filename (str ou None) → chemin relatif sous /static/uploads/...
          - user_id (int)
        """
        try:
            # 1) Validation des champs “titre” et “contenu”
            validation_result = self.validate_article_data(title, content)
            if not validation_result["valid"]:
                return {"success": False, "error": validation_result["error"]}

            # 2) Appel à la couche basse (Database) pour créer l’article
            article_id = self.db.create_article(
                title=title,
                description=description,
                content=content,
                image_filename=image_filename,
                author_id=user_id
            )
            if not article_id:
                return {
                    "success": False,
                    "error": "Erreur lors de la création de l’article"
                }

            return {"success": True, "article_id": article_id}

        except Exception:
            logger.exception("Erreur inattendue dans create_article")
            return {"success": False, "error": "Erreur lors de la création de l’article"}

    def edit_article(self, article_id, title, description, content, image_filename, user_id):
        """
        Edit an existing article.  
        Paramètres :
          - article_id   (int)
          - title        (str)
          - description  (str ou "")
          - content      (str)
          - image_filename (str ou None) → chemin relatif en base
          - user_id      (int)
        """
        try:
            # 1) Vérifier que l’article existe et qu’on est bien l’auteur
            article = self.db.get_article_by_id(article_id)
            if not article or article["author_id"] != user_id:
                return {"success": False, "error": "Article non trouvé ou non autorisé"}

            # 2) Validation des champs “titre” et “contenu”
            validation_result = self.validate_article_data(title, content)
            if not validation_result["valid"]:
                return {"success": False, "error": validation_result["error"]}

            # 3) Mise à jour dans la DB
            success = self.db.update_article(
                article_id=article_id,
                title=title,
                description=description,
                content=content,
                image_filename=image_filename
            )
            if not success:
                return {
                    "success": False,
                    "error": "Erreur lors de la modification de l’article"
                }

            return {"success": True}

        except Exception:
            logger.exception("Erreur inattendue dans edit_article")
            return {"success": False, "error": "Erreur lors de la modification de l’article"}

    def delete_article(self, article_id, user_id):
        """Delete an article"""
        try:
            # Check if article exists and belongs to user
            article = self.db.get_article_by_id(article_id)
            if not article or article['author_id'] != user_id:
                return {'success': False, 'error': 'Article non trouvé ou non autorisé'}

            # Delete article
            success = self.db.delete_article(article_id, user_id)
            if not success:
                return {'success': False, 'error': 'Erreur lors de la suppression de l\'article'}

            return {'success': True}

        except Exception:
            logger.exception("Erreur inattendue dans delete_article")
            return {'success': False, 'error': 'Erreur lors de la suppression de l\'article'}

    def toggle_like(self, article_id, user_id):
        """Toggle like status for an article"""
        try:
            # Check if article exists
            article = self.db.get_article_by_id(article_id)
            if not article:
                return {'success': False, 'error': 'Article non trouvé'}

            # Toggle like
            result = self.db.toggle_like(article_id, user_id)
            return {
                'success': True,
                'liked': result['liked'],
                'likes_count': result['likes_count']
            }

        except Exception:
            logger.exception("Erreur inattendue dans toggle_like")
            return {'success': False, 'error': 'Erreur lors du like'}

    def toggle_save(self, article_id, user_id):
        """Toggle save status for an article"""
        try:
            # Check if article exists
            article = self.db.get_article_by_id(article_id)
            if not article:
                return {'success': False, 'error': 'Article non trouvé'}

            # Toggle save
            result = self.db.toggle_save(article_id, user_id)
            return {
                'success': True,
                'saved': result['saved']
            }

        except Exception:
            logger.exception("Erreur inattendue dans toggle_save")
            return {'success': False, 'error': 'Erreur lors de la sauvegarde'}

    def add_comment(self, article_id, form, user_id):
        """Add a comment to an article (form : request.form ou tout dictionnaire)"""
        try:
            # Check if article exists
            article = self.db.get_article_by_id(article_id)
            if not article:
                return {'success': False, 'error': 'Article non trouvé'}

            content = form.get('content', '').strip()

            # Validate comment
            if not content:
                return {'success': False, 'error': 'Le commentaire ne peut pas être vide'}

            if len(content) > 1000:
                return {'success': False, 'error': 'Le commentaire ne peut pas dépasser 1000 caractères'}

            # Add comment
            comment_id = self.db.add_comment(article_id, user_id, content)
            if not comment_id:
                return {'success': False, 'error': 'Erreur lors de l\'ajout du commentaire'}

            # Get updated comments
            comments = self.db.get_article_comments(article_id)
            return {
                'success': True,
                'comment_id': comment_id,
                'comments': comments,
                'comments_count': len(comments)
            }

        except Exception:
            logger.exception("Erreur inattendue dans add_comment")
            return {'success': False, 'error': 'Erreur lors de l\'ajout du commentaire'}

    def validate_article_data(self, title, content):
        """Validate article form data"""
        # Check if required fields are filled
        if not title:
            return {'valid': False, 'error': 'Le titre est obligatoire'}

        if not content:
            return {'valid': False, 'error': 'Le contenu est obligatoire'}

        # Validate title
        if len(title) < 5:
            return {'valid': False, 'error': 'Le titre doit contenir au moins 5 caractères'}

        if len(title) > 200:
            return {'valid': False, 'error': 'Le titre ne peut pas dépasser 200 caractères'}

        # Validate content
        if len(content) < 10:
            return {'valid': False, 'error': 'Le contenu doit contenir au moins 10 caractères'}

        if len(content) > 10000:
            return {'valid': False, 'error': 'Le contenu ne peut pas dépasser 10000 caractères'}

        return {'valid': True}