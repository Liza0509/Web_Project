from app import app, db
from models import User  # если у тебя модели в отдельном файле models.py

with app.app_context():
    admin = User(username='admin', email='admin@example.com', role='admin')
    admin.set_password('pass')  # или другой пароль
    db.session.add(admin)
    db.session.commit()
    print("Admin user created!")
