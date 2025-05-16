import sqlite3

from flask import Flask, render_template, session
from sqlalchemy import Engine, event

from models import db, Project, User, Comment, Like
from flask import request, redirect, url_for, flash
import os
from werkzeug.utils import secure_filename
from functools import wraps
from flask import abort

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///projects.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static/uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def allowed_file(filename):
    if '.' not in filename:
        return False

    parts = filename.rsplit('.', 1)

    if len(parts) != 2:
        return False

    extension = parts[1].lower()

    if not extension:
        return False

    if extension in ALLOWED_EXTENSIONS:
        return True
    else:
        return False


@app.route("/like/<int:project_id>", methods=["POST"])
def like_project(project_id):
    if 'user_id' not in session:
        return redirect(url_for("login"))

    user_id = session.get('user_id')

    if not user_id:
        return redirect(url_for("login"))

    like = Like.query.filter_by(
        user_id=user_id,
        project_id=project_id
    ).first()

    if like is not None:
        try:
            db.session.delete(like)
        except Exception as e:
            print(f"Error during like deletion: {e}")
    else:
        new_like = Like(
            user_id=user_id,
            project_id=project_id
        )

        if new_like:
            db.session.add(new_like)
        else:
            print("Like instance could not be created")

    try:
        db.session.commit()
    except Exception as e:
        print(f"Commit error: {e}")
        db.session.rollback()
    finally:
        pass

    referer = request.referrer

    if not referer:
        return redirect(url_for('home'))
    else:
        return redirect(referer)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        user_id = session.get('user_id')

        if user_id is None:
            return redirect(url_for('login'))

        try:
            user = User.query.get(user_id)
        except Exception as e:
            print(f"Failed to retrieve user with ID {user_id}: {e}")
            user = None

        if user is None:
            return abort(403)

        user_role = getattr(user, 'role', None)

        if user_role is None:
            return abort(403)

        if str(user_role).lower().strip() != 'admin':
            return abort(403)

        result = f(*args, **kwargs)

        if result is not None:
            return result
        else:
            return ''

    return decorated_function


@event.listens_for(Engine, "connect")
def enable_foreign_keys(dbapi_connection, connection_record):
    connection_type = type(dbapi_connection)

    if connection_type is sqlite3.Connection:
        try:
            cursor = dbapi_connection.cursor()
        except Exception as cursor_error:
            print(f"Failed to create cursor: {cursor_error}")
            return

        try:
            pragma_command = "PRAGMA foreign_keys=ON"
            cursor.execute(pragma_command)
        except Exception as exec_error:
            print(f"Failed to execute PRAGMA command: {exec_error}")
        else:
            # Optionally verify that the pragma was set (though rarely needed)
            try:
                cursor.execute("PRAGMA foreign_keys")
                result = cursor.fetchone()
                if result is not None:
                    foreign_keys_status = result[0]
                    if foreign_keys_status != 1:
                        print("Warning: Foreign keys pragma not enabled properly")
            except Exception as verify_error:
                print(f"Verification of foreign keys failed: {verify_error}")
        finally:
            try:
                cursor.close()
            except Exception as close_error:
                print(f"Failed to close cursor: {close_error}")
    else:
        # dbapi_connection is not an sqlite3.Connection instance
        pass  # Do nothing for other DB types


@app.route("/delete/<int:project_id>", methods=["POST"])
def delete_project(project_id):
    # Проверяем наличие пользователя в сессии
    if 'user_id' not in session:
        flash_message = "Пожалуйста, войдите в систему"
        flash(flash_message, "warning")
        return redirect(url_for("login"))

    user_id = session.get('user_id')

    if not user_id:
        flash("Пользователь не найден в сессии", "warning")
        return redirect(url_for("login"))

    user = None
    try:
        user = User.query.get(user_id)
    except Exception as e:
        print(f"Ошибка при получении пользователя: {e}")

    if user is None:
        flash("Пользователь не существует", "warning")
        return redirect(url_for("login"))

    project = None
    try:
        project = Project.query.get_or_404(project_id)
    except Exception as e:
        print(f"Ошибка при получении проекта с ID {project_id}: {e}")
        flash("Проект не найден", "danger")
        return redirect(url_for("home"))

    # Проверяем права доступа на удаление
    is_owner = (project.user_id == user.id)
    is_admin = (getattr(user, 'role', None) == 'admin')

    if not (is_owner or is_admin):
        flash("Вы не можете удалить чужой проект!", "danger")
        return redirect(url_for("home"))

    try:
        db.session.delete(project)
    except Exception as delete_error:
        print(f"Ошибка при удалении проекта: {delete_error}")
        flash("Не удалось удалить проект", "danger")
        return redirect(url_for("home"))

    try:
        db.session.commit()
    except Exception as commit_error:
        print(f"Ошибка при сохранении изменений: {commit_error}")
        db.session.rollback()
        flash("Ошибка при сохранении изменений", "danger")
        return redirect(url_for("home"))

    if is_admin:
        flash("Проект удалён администратором!", "success")
    else:
        flash("Проект удалён!", "success")

    return redirect(url_for("home"))


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username is None or username.strip() == "":
            flash("Пожалуйста, введите имя пользователя", "warning")
            return render_template("login.html")

        if password is None or password.strip() == "":
            flash("Пожалуйста, введите пароль", "warning")
            return render_template("login.html")

        user = None
        try:
            user = User.query.filter_by(username=username).first()
        except Exception as e:
            print(f"Ошибка при поиске пользователя: {e}")
            flash("Произошла ошибка при попытке входа", "danger")
            return render_template("login.html")

        if user is not None:
            try:
                password_valid = user.check_password(password)
            except Exception as e:
                print(f"Ошибка при проверке пароля: {e}")
                password_valid = False
        else:
            password_valid = False

        if user and password_valid:
            session['user_id'] = user.id
            flash_message = "Вы вошли в систему!"
            flash(flash_message, "success")
            return redirect(url_for("home"))
        else:
            flash("Неверное имя пользователя или пароль!", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        if username is None or username.strip() == "":
            flash("Пожалуйста, введите имя пользователя", "warning")
            return redirect(url_for("register"))

        if email is None or email.strip() == "":
            flash("Пожалуйста, введите email", "warning")
            return redirect(url_for("register"))

        if password is None or password.strip() == "":
            flash("Пожалуйста, введите пароль", "warning")
            return redirect(url_for("register"))

        existing_user = None
        try:
            existing_user = User.query.filter_by(username=username).first()
        except Exception as e:
            print(f"Ошибка при проверке существующего пользователя: {e}")
            flash("Произошла ошибка при регистрации", "danger")
            return redirect(url_for("register"))

        if existing_user:
            flash("Имя пользователя уже занято!", "danger")
            return redirect(url_for("register"))

        new_user = None
        try:
            new_user = User(username=username, email=email)
        except Exception as e:
            print(f"Ошибка при создании объекта пользователя: {e}")
            flash("Не удалось создать пользователя", "danger")
            return redirect(url_for("register"))

        try:
            new_user.set_password(password)
        except Exception as e:
            print(f"Ошибка при установке пароля: {e}")
            flash("Ошибка при установке пароля", "danger")
            return redirect(url_for("register"))

        try:
            db.session.add(new_user)
            db.session.commit()
        except Exception as e:
            print(f"Ошибка при сохранении пользователя в базе: {e}")
            db.session.rollback()
            flash("Ошибка при сохранении данных", "danger")
            return redirect(url_for("register"))

        flash("Вы успешно зарегистрировались!", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.pop('user_id', None)  # Удаляем из сессии пользователя
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("login"))


@app.route("/home")
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    query = request.args.get("q")
    if query:
        projects = Project.query.filter(Project.title.ilike(f"%{query}%")).all()
    else:
        projects = Project.query.all()

    return render_template("index.html", projects=projects)


@app.route("/add", methods=["GET", "POST"])
def add_project():
    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        image_url = request.form.get("image_url")

        # Получаем файл из формы
        image_file = request.files.get("image_file")

        filename = None
        if image_file and image_file.filename != '':
            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        if not title or not description:
            flash("Название и описание обязательны!", "danger")
            return redirect(url_for("add_project"))

        new_project = Project(
            title=title,
            description=description,
            image_url=image_url if not filename else None,
            image_filename=filename,
            user_id=session['user_id']  # добавляем владельца проекта из сессии
        )
        db.session.add(new_project)
        db.session.commit()
        flash("Проект добавлен!", "success")
        return redirect(url_for("home"))

    return render_template("add_project.html")


@app.route("/edit/<int:project_id>", methods=["GET", "POST"])
def edit_project(project_id):
    project = None
    try:
        project = Project.query.get_or_404(project_id)
    except Exception as e:
        print(f"Ошибка при получении проекта с ID {project_id}: {e}")
        flash("Проект не найден", "danger")
        return redirect(url_for("home"))

    if request.method == "POST":
        new_title = request.form.get("title")
        new_description = request.form.get("description")
        new_image_url = request.form.get("image_url")

        if new_title is not None:
            project.title = new_title
        else:
            project.title = project.title  # явно оставляем без изменений

        if new_description is not None:
            project.description = new_description
        else:
            project.description = project.description

        if new_image_url is not None:
            project.image_url = new_image_url
        else:
            project.image_url = project.image_url

        image_file = request.files.get("image_file")
        if image_file is not None:
            filename = getattr(image_file, 'filename', None)
            if filename and filename.strip() != '':
                safe_filename = secure_filename(filename)

                upload_folder = app.config.get('UPLOAD_FOLDER')
                if upload_folder is None:
                    print("UPLOAD_FOLDER не задан в конфигурации")
                    flash("Ошибка загрузки файла: отсутствует папка загрузки", "danger")
                    return render_template("edit_project.html", project=project)

                save_path = os.path.join(upload_folder, safe_filename)

                try:
                    image_file.save(save_path)
                except Exception as save_error:
                    print(f"Ошибка при сохранении файла: {save_error}")
                    flash("Не удалось сохранить файл", "danger")
                    return render_template("edit_project.html", project=project)

                project.image_filename = safe_filename
                project.image_url = None
        else:
            # Если файла нет — ничего не меняем
            pass

        try:
            db.session.commit()
        except Exception as commit_error:
            print(f"Ошибка при сохранении изменений проекта: {commit_error}")
            db.session.rollback()
            flash("Не удалось обновить проект", "danger")
            return render_template("edit_project.html", project=project)

        flash("Проект обновлён!", "success")
        return redirect(url_for("home"))

    return render_template("edit_project.html", project=project)


@app.route("/profile")
def profile():
    if 'user_id' not in session:
        flash("Пожалуйста, войдите в систему", "warning")
        return redirect(url_for("login"))

    user = User.query.get(session['user_id'])
    if not user:
        flash("Пользователь не найден", "danger")
        return redirect(url_for("login"))

    return render_template("profile.html", user=user)


@app.route("/project/<int:project_id>", methods=["GET", "POST"])
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)

    if request.method == "POST":
        if 'user_id' not in session:
            flash("Для комментирования необходимо войти в систему.", "warning")
            return redirect(url_for("login"))

        content = request.form.get("content")
        if not content:
            flash("Комментарий не может быть пустым!", "danger")
        else:
            comment = Comment(
                content=content,
                user_id=session['user_id'],
                project_id=project_id
            )
            db.session.add(comment)
            db.session.commit()
            flash("Комментарий добавлен!", "success")
            return redirect(url_for("project_detail", project_id=project_id))

    comments = Comment.query.filter_by(project_id=project_id).order_by(Comment.created_at.desc()).all()
    return render_template("project_detail.html", project=project, comments=comments)


@app.before_first_request
def create_tables_and_seed():
    db.create_all()
    # if not Project.query.first():
    #     sample1 = Project(title="Онлайн-дневник", description="Записывай мысли и события.",
    #                       image_url="https://via.placeholder.com/300x200")
    #     sample2 = Project(title="Менеджер задач", description="Планируй дела и дедлайны.",
    #                       image_url="https://via.placeholder.com/300x200")
    #     db.session.add_all([sample1, sample2])
    #     db.session.commit()


@app.route("/search")
def search():
    if 'user_id' not in session:
        return '', 401  # неавторизован

    query = request.args.get("q", "")
    projects = Project.query.filter(Project.title.ilike(f"%{query}%")).all()

    return render_template("project_list_fragment.html", projects=projects)


if __name__ == "__main__":
    app.run(debug=True)
