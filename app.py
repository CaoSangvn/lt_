from flask import Flask, render_template, request, redirect, url_for, session, g, flash
from flask_socketio import SocketIO, emit
import sqlite3, os, base64
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from ftp_upload import upload_file_ftp
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'
socketio = SocketIO(app)

# Cấu hình thư mục
IMAGE_FOLDER = 'static/image/uploads'
FILE_FOLDER = 'static/files/uploads'
os.makedirs(IMAGE_FOLDER, exist_ok=True)
os.makedirs(FILE_FOLDER, exist_ok=True)

app.config['UPLOAD_IMAGE_FOLDER'] = IMAGE_FOLDER
app.config['UPLOAD_FILE_FOLDER'] = FILE_FOLDER
app.config['DATABASE'] = 'chat.db'

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
ALLOWED_FILE_EXTENSIONS = {'pdf', 'docx', 'doc', 'xlsx', 'xls', 'txt', 'pptx'}

def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_FILE_EXTENSIONS


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_connection(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ------------------ Đăng ký ------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if not username or not password or password != confirm_password:
            flash("Thông tin đăng ký không hợp lệ.")
            return render_template('register.html')

        conn = get_db()
        existing = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            flash("Tên đăng nhập đã tồn tại.")
            return render_template('register.html')

        hashed = generate_password_hash(password)
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hashed, 'user'))
        conn.commit()
        flash("Đăng ký thành công!")
        return redirect(url_for('login'))
    return render_template('register.html')

# ------------------ Đăng nhập ------------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['username'] = username
            return redirect(url_for('chat'))
        else:
            flash("Sai tên đăng nhập hoặc mật khẩu.")
    return render_template('login.html')

# ------------------ Chat ------------------

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    messages = db.execute('SELECT * FROM chat ORDER BY timestamp ASC').fetchall()

    return render_template('chat.html', username=session['username'], messages=messages)


# ------------------ SocketIO nhận và gửi tin nhắn ------------------
@socketio.on('send_message')
def handle_send_message(data):
    username = session.get('username', 'Ẩn danh')
    message = data.get('message', '')
    image_data = data.get('image')
    file_data = data.get('file')

    image_url = None
    file_url = None

    # Xử lý ảnh
    if image_data:
        filename = secure_filename(image_data['filename'])
        if allowed_image(filename):
            filepath = os.path.join(app.config['UPLOAD_IMAGE_FOLDER'], filename)
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(image_data['data'].split(',')[1]))
            image_url = f'/static/image/uploads/{filename}'

    # Xử lý file
    if file_data:
        filename = secure_filename(file_data['filename'])
        if allowed_file(filename):
            filepath = os.path.join(app.config['UPLOAD_FILE_FOLDER'], filename)
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(file_data['data'].split(',')[1]))
            file_url = f'/static/files/uploads/{filename}'

    # 👉 Lưu tin nhắn vào CSDL
    db = get_db()
    db.execute('INSERT INTO chat (username, message, image_path, file_path) VALUES (?, ?, ?, ?)',
               (username, message, image_url, file_url))
    db.commit()

    # Phát lại tin nhắn
    emit('receive_message', {
        'user': username,
        'message': message,
        'image': image_url,
        'file': file_url
    }, broadcast=True)
    
# ------------------ Đăng xuất ------------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    socketio.run(app, debug=True)
