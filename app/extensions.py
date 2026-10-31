"""Flask extension singletons.

They are created here (un-bound) and initialised inside ``create_app`` so the
application factory pattern works and tests can build isolated app instances.
"""

from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate(render_as_batch=True)  # batch mode so ALTER TABLE works on SQLite
bcrypt = Bcrypt()
csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"
