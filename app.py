from flask import Flask, render_template, request, redirect, url_for, session, g, flash
from flask_socketio import SocketIO, emit
import sqlite3, os, base64
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

import google.generativeai as genai
from dotenv import load_dotenv
import requests

# --- TẢI VÀ CẤU HÌNH CÁC DỊCH VỤ ---
load_dotenv()

# Cấu hình AI
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Lỗi: Không tìm thấy GEMINI_API_KEY trong file .env")
        ai_model = None
    else:
        genai.configure(api_key=api_key)
        ai_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("✅ Khởi tạo mô hình AI thành công với 'gemini-1.5-flash-latest'.")
except Exception as e:
    print(f"❌ Lỗi khởi tạo mô hình AI: {e}")
    ai_model = None

# Lấy API key thời tiết
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

app = Flask(__name__)
# ... (Phần còn lại của cấu hình và các hàm không đổi giữ nguyên) ...
app.secret_key = 'your_secret_key'
socketio = SocketIO(app)
IMAGE_FOLDER, FILE_FOLDER = 'static/image/uploads', 'static/files/uploads'
os.makedirs(IMAGE_FOLDER, exist_ok=True)
os.makedirs(FILE_FOLDER, exist_ok=True)
app.config.update(UPLOAD_IMAGE_FOLDER=IMAGE_FOLDER, UPLOAD_FILE_FOLDER=FILE_FOLDER, DATABASE='chat.db')
ALLOWED_IMAGE_EXTENSIONS, ALLOWED_FILE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}, {'pdf', 'docx', 'doc', 'xlsx', 'xls', 'txt', 'pptx'}
def allowed_image(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
def allowed_file(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_FILE_EXTENSIONS
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close_connection(exception):
    db = g.pop('db', None)
    if db is not None: db.close()
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'quanly':
            flash('Bạn không có quyền truy cập trang này.')
            return redirect(url_for('chat'))
        return f(*args, **kwargs)
    return decorated_function
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username, password, confirm_password = request.form['username'].strip(), request.form['password'], request.form['confirm_password']
        if not username or not password or password != confirm_password:
            flash("Thông tin đăng ký không hợp lệ.")
            return render_template('register.html')
        try:
            conn = get_db()
            if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
                flash("Tên đăng nhập này đã tồn tại.")
                return render_template('register.html')
            conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, generate_password_hash(password), 'nhanvien'))
            conn.commit()
            flash("Đăng ký tài khoản thành công! Bây giờ bạn có thể đăng nhập.")
            return redirect(url_for('login'))
        except sqlite3.Error as e:
            flash(f"Đã có lỗi xảy ra với cơ sở dữ liệu: {e}")
            return render_template('register.html')
    return render_template('register.html')
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username, password = request.form['username'].strip(), request.form['password']
        user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session.update(username=username, role=user['role'])
            return redirect(url_for('admin') if user['role'] == 'quanly' else url_for('chat'))
        else:
            flash("Sai tên đăng nhập hoặc mật khẩu.")
    return render_template('login.html')
@app.route('/admin')
@admin_required
def admin(): return render_template('admin.html', users=get_db().execute('SELECT id, username, role FROM users ORDER BY id').fetchall())
@app.route('/admin/history')
@admin_required
def chat_history(): return render_template('chat_history.html', messages=get_db().execute('SELECT * FROM chat ORDER BY timestamp DESC').fetchall())
@app.route('/chat')
def chat():
    if 'username' not in session: return redirect(url_for('login'))
    return render_template('chat.html', username=session['username'], messages=get_db().execute('SELECT * FROM chat ORDER BY timestamp ASC').fetchall())
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- CÁC HÀM TRỢ GIÚP ---

def extract_city_from_prompt(prompt):
    """Trích xuất tên thành phố từ câu hỏi của người dùng."""
    words = prompt.split()
    # Tìm các từ được viết hoa, thường là tên riêng
    capitalized_words = [word for word in words if word.istitle() and word.lower() != 'thời' and word.lower() != 'tiết']
    if capitalized_words:
        return " ".join(capitalized_words)
    return None # Trả về None nếu không tìm thấy

def get_current_weather(city="Hanoi"):
    """Hàm lấy dữ liệu thời tiết từ OpenWeatherMap."""
    if not WEATHER_API_KEY:
        return "Lỗi: Chưa cấu hình API key cho dịch vụ thời tiết."
    
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=vi"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        description = data['weather'][0]['description']
        temp = data['main']['temp']
        city_name = data['name']
        return f"Thời tiết tại {city_name} hiện tại: {temp}°C, {description}."
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return f"Xin lỗi, tôi không tìm thấy thông tin cho thành phố '{city}'."
        print(f"Lỗi HTTP khi gọi API thời tiết: {e}")
        return "Xin lỗi, tôi không thể lấy dữ liệu thời tiết lúc này."
    except requests.exceptions.RequestException as e:
        print(f"Lỗi kết nối khi gọi API thời tiết: {e}")
        return "Xin lỗi, tôi không thể lấy dữ liệu thời tiết lúc này."

def get_ai_response(prompt):
    """Gửi yêu cầu đến AI và nhận câu trả lời."""
    if not ai_model:
        return "Lỗi: Mô hình AI chưa được khởi tạo. Vui lòng kiểm tra lại API key."
    try:
        response = ai_model.generate_content(prompt)
        cleaned_text = response.text.replace('*', '').strip()
        return cleaned_text
    except Exception as e:
        print(f"Lỗi khi gọi API của AI: {e}")
        return "Xin lỗi, tôi gặp lỗi khi xử lý yêu cầu của bạn."

def _save_file(file_data, upload_folder, allowed_extensions_func):
    if not file_data: return None, None
    original_filename = file_data['filename']
    if not allowed_extensions_func(original_filename): return None, None
    new_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(original_filename)}"
    filepath = os.path.join(upload_folder, new_filename)
    try:
        with open(filepath, 'wb') as f: f.write(base64.b64decode(file_data['data'].split(',')[1]))
        return f"/static/{upload_folder.split('static/')[1]}/{new_filename}", original_filename
    except Exception as e:
        print(f"Lỗi khi lưu file: {e}")
        return None, None

# --- CẬP NHẬT LOGIC SOCKET.IO ---
@socketio.on('send_message')
def handle_send_message(data):
    username = session.get('username', 'Ẩn danh')
    message = data.get('message', '').strip()
    
    # Gửi và lưu tin nhắn gốc của người dùng
    image_url, _ = _save_file(data.get('image'), app.config['UPLOAD_IMAGE_FOLDER'], allowed_image)
    file_url, original_filename = _save_file(data.get('file'), app.config['UPLOAD_FILE_FOLDER'], allowed_file)
    db = get_db()
    db.execute('INSERT INTO chat (username, message, image_path, file_path) VALUES (?, ?, ?, ?)',
               (username, message, image_url, file_url))
    db.commit()
    emit('receive_message', {'user': username, 'message': message, 'image': image_url, 'file_info': {'url': file_url, 'name': original_filename} if file_url else None}, broadcast=True)

    # Xử lý logic cho Bot
    if message.lower().startswith('@bot'):
        prompt = message[4:].strip()
        bot_response_text = ""
        
        socketio.emit('receive_message', {'user': 'Bot', 'message': 'Đang suy nghĩ...'})

        # Kiểm tra intent của người dùng
        if 'thời tiết' in prompt.lower():
            city = extract_city_from_prompt(prompt) or "Hanoi" # Trích xuất thành phố, nếu không có thì mặc định là Hanoi
            weather_data = get_current_weather(city)
            final_prompt = f"Dựa vào thông tin sau: '{weather_data}', hãy trả lời câu hỏi của người dùng một cách thân thiện và ngắn gọn."
            bot_response_text = get_ai_response(final_prompt)
        elif not prompt:
             bot_response_text = "Bạn muốn hỏi tôi điều gì?"
        else:
            bot_response_text = get_ai_response(prompt)
        
        # Gửi câu trả lời của Bot
        db.execute('INSERT INTO chat (username, message) VALUES (?, ?)', ('Bot', bot_response_text))
        db.commit()
        socketio.emit('receive_message', {'user': 'Bot', 'message': bot_response_text})

# --- KHỞI CHẠY ỨNG DỤNG ---
if __name__ == '__main__':
    socketio.run(app, debug=True)