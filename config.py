import os

class Config:
    SECRET_KEY = os.urandom(24)
    SQLALCHEMY_DATABASE_URI = "sqlite:///legal_consulting.db"  # Change to your Heroku DB in production
    SQLALCHEMY_TRACK_MODIFICATIONS = False
