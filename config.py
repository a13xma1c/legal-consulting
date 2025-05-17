import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkeychangeme")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///site.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
