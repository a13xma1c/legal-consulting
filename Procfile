release: uv run flask --app wsgi db upgrade
web: uv run gunicorn wsgi:app --workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-4}
