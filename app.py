import logging
from app import create_app

# Create the Flask application using the factory
app = create_app()

# Configure logging
if not app.debug:
    # Log errors to a file in production
    file_handler = logging.FileHandler("error.log")
    file_handler.setLevel(logging.ERROR)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    app.logger.addHandler(file_handler)

# Entry point for the application
if __name__ == "__main__":
    # Let Gunicorn handle the server in production; app.run is for local only
    app.run(host="0.0.0.0", port=5000)
