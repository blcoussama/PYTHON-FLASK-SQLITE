import logging

import re

logger = logging.getLogger(__name__)


class AuthHandler:
    def __init__(self, database):
        self.db = database

    def login(self, form):
        """Handle user login (form : request.form ou tout dictionnaire)"""
        try:
            username = form.get('username', '').strip()
            password = form.get('password', '')

            # Validate input
            if not username or not password:
                return {'success': False, 'error': 'Veuillez remplir tous les champs'}

            # Check credentials
            user = self.db.get_user_by_credentials(username, password)
            if not user:
                return {'success': False, 'error': 'Nom d\'utilisateur ou mot de passe incorrect'}

            return {'success': True, 'user': user}

        except Exception:
            logger.exception("Erreur inattendue dans login")
            return {'success': False, 'error': 'Erreur lors de la connexion'}

    def register(self, form):
        """Handle user registration (form : request.form ou tout dictionnaire)"""
        try:
            username = form.get('username', '').strip()
            email = form.get('email', '').strip().lower()
            password = form.get('password', '')
            confirm_password = form.get('confirm_password', '')

            # Validate input
            validation_result = self.validate_registration_data(username, email, password, confirm_password)
            if not validation_result['valid']:
                return {'success': False, 'error': validation_result['error']}

            # Check if user already exists
            if self.db.get_user_by_username(username):
                return {'success': False, 'error': 'Ce nom d\'utilisateur existe déjà'}

            if self.db.get_user_by_email(email):
                return {'success': False, 'error': 'Cette adresse email est déjà utilisée'}

            # Create user
            user = self.db.create_user(username, email, password)
            if not user:
                return {'success': False, 'error': 'Erreur lors de la création du compte'}

            return {'success': True, 'user': user}

        except Exception:
            logger.exception("Erreur inattendue dans register")
            return {'success': False, 'error': 'Erreur lors de l\'inscription'}

    def validate_registration_data(self, username, email, password, confirm_password):
        """Validate registration form data"""
        # Check if all fields are filled
        if not all([username, email, password, confirm_password]):
            return {'valid': False, 'error': 'Veuillez remplir tous les champs'}

        # Validate username
        if len(username) < 3:
            return {'valid': False, 'error': 'Le nom d\'utilisateur doit contenir au moins 3 caractères'}
        
        if len(username) > 20:
            return {'valid': False, 'error': 'Le nom d\'utilisateur ne peut pas dépasser 20 caractères'}

        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return {'valid': False, 'error': 'Le nom d\'utilisateur ne peut contenir que des lettres, chiffres et underscore'}

        # Validate email
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return {'valid': False, 'error': 'Adresse email invalide'}

        # Validate password
        if len(password) < 8:
            return {'valid': False, 'error': 'Le mot de passe doit contenir au moins 8 caractères'}

        if len(password) > 100:
            return {'valid': False, 'error': 'Le mot de passe ne peut pas dépasser 100 caractères'}

        # Check password confirmation
        if password != confirm_password:
            return {'valid': False, 'error': 'Les mots de passe ne correspondent pas'}

        return {'valid': True}