from app import create_app, db
from app.models import User, Consultation

# Initialize the app
app = create_app()

# For interactive debugging or database migrations
@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'User': User, 'Consultation': Consultation}

if __name__ == "__main__":
    app.run(debug=True)