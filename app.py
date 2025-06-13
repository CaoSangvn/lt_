from flask import Flask, render_template, request, redirect, url_for, session, g, flash
from flask_socketio import SocketIO, emit
import sqlite3, os, base64, re, unicodedata
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import google.generativeai as genai
from dotenv import load_dotenv
import requests

from googlesearch import search
from bs4 import BeautifulSoup

# --- TẢI VÀ CẤU HÌNH CÁC DỊCH VỤ ---
load_dotenv()
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
    
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

app = Flask(__name__)
app.secret_key = 'your_secret_key'
socketio = SocketIO(app)

# Cấu hình thư mục
IMAGE_FOLDER, FILE_FOLDER = 'static/image/uploads', 'static/files/uploads'
AVATAR_FOLDER = 'static/avatars'
os.makedirs(IMAGE_FOLDER, exist_ok=True)
os.makedirs(FILE_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)

app.config.update(
    UPLOAD_IMAGE_FOLDER=IMAGE_FOLDER, 
    UPLOAD_FILE_FOLDER=FILE_FOLDER,
    UPLOAD_AVATAR_FOLDER=AVATAR_FOLDER,
    DATABASE='chat.db'
)

ALLOWED_IMAGE_EXTENSIONS, ALLOWED_FILE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}, {'pdf', 'docx', 'doc', 'xlsx', 'xls', 'txt', 'pptx'}
def allowed_image(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
def allowed_file(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_FILE_EXTENSIONS

# --- QUẢN LÝ DATABASE VÀ SESSION ---
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_connection(exception):
    db = g.pop('db', None)
    if db is not None: db.close()

# --- DECORATORS ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'quanly':
            flash('Bạn không có quyền truy cập trang này.', 'error')
            return redirect(url_for('chat'))
        return f(*args, **kwargs)
    return decorated_function

# --- HÀM TRỢ GIÚP ---
def process_messages_timestamps(raw_messages):
    messages = []
    local_tz = timezone(timedelta(hours=7))
    for msg in raw_messages:
        msg_dict = dict(msg)
        if msg_dict.get('timestamp'):
            try:
                utc_dt_naive = datetime.strptime(msg_dict['timestamp'], '%Y-%m-%d %H:%M:%S')
                utc_dt_aware = utc_dt_naive.replace(tzinfo=timezone.utc)
                local_dt = utc_dt_aware.astimezone(local_tz)
                msg_dict['timestamp'] = local_dt
            except (ValueError, TypeError):
                msg_dict['timestamp'] = None
        messages.append(msg_dict)
    return messages

# --- CÁC ROUTE CƠ BẢN (ĐĂNG NHẬP, ĐĂNG KÝ, ĐĂNG XUẤT) ---
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
    session.clear()
    if request.method == 'POST':
        username, password = request.form['username'].strip(), request.form['password']
        user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session.update(username=username, role=user['role'], user_id=user['id'])    
            return redirect(url_for('admin') if user['role'] == 'quanly' else url_for('chat'))
        else:
            flash("Sai tên đăng nhập hoặc mật khẩu.")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash("Bạn đã đăng xuất thành công.")
    return redirect(url_for('login'))

# --- ROUTE TRANG PROFILE (TÍNH NĂNG MỚI) ---
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if user is None:
        session.clear()
        flash("Không tìm thấy thông tin người dùng, vui lòng đăng nhập lại.", "error")
        return redirect(url_for('login'))
    if request.method == 'POST':
        file = request.files.get('avatar')
        if file and allowed_image(file.filename):
            # Xóa avatar cũ nếu có và không phải là ảnh mặc định
            if user['avatar_path'] and user['avatar_path'] != '/static/image/avatar_placeholder.png':
                try:
                    # Tạo đường dẫn tuyệt đối an toàn
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    old_file_path = os.path.join(base_dir, user['avatar_path'].lstrip('/'))
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                except OSError as e:
                    print(f"Lỗi khi xóa file cũ: {e}")

            # Lưu avatar mới
            filename = f"user_{session['user_id']}_{secure_filename(file.filename)}"
            filepath = os.path.join(app.config['UPLOAD_AVATAR_FOLDER'], filename)
            file.save(filepath)
            
            # Cập nhật đường dẫn trong database
            avatar_path = f"/{filepath.replace(os.path.sep, '/')}"
            db.execute('UPDATE users SET avatar_path = ? WHERE id = ?', (avatar_path, session['user_id']))
            db.commit()
            
            flash('Cập nhật avatar thành công!')
            return redirect(url_for('profile'))

    return render_template('profile.html', user=user)

# --- CÁC ROUTE TRANG CHAT ---
@app.route('/chat')
@login_required
def chat():
    db = get_db()
    latest_announcement = db.execute('SELECT * FROM announcements ORDER BY created_at DESC LIMIT 1').fetchone()
    messages_raw = db.execute('''
        SELECT c.*, u.avatar_path
        FROM chat c 
        JOIN users u ON c.username = u.username
        ORDER BY c.timestamp ASC
    ''').fetchall()
    
    return render_template('chat.html', 
                           username=session['username'], 
                           messages=process_messages_timestamps(messages_raw), 
                           announcement=latest_announcement)

# --- CÁC ROUTE CỦA ADMIN ---
@app.route('/admin')
@admin_required
def admin(): return render_template('admin.html', users=get_db().execute('SELECT id, username, role FROM users ORDER BY id').fetchall())

@app.route('/admin/history')
@admin_required
def chat_history():
    return render_template('chat_history.html', messages=process_messages_timestamps(get_db().execute('SELECT * FROM chat ORDER BY timestamp DESC').fetchall()))

@app.route('/admin/clear_history', methods=['POST'])
@admin_required
def clear_chat_history():
    try:
        db = get_db()
        db.execute('DELETE FROM chat')
        db.commit()
        flash('Toàn bộ lịch sử trò chuyện đã được xóa thành công!', 'success')
    except sqlite3.Error as e:
        flash(f'Đã có lỗi xảy ra khi xóa lịch sử: {e}', 'error')
    return redirect(url_for('chat_history'))

@app.route('/admin/announce', methods=['POST'])
@admin_required
def send_announcement():
    content = request.form.get('content')
    admin_username = session.get('username')
    if not content or not content.strip():
        flash('Nội dung thông báo không được để trống.', 'error')
        return redirect(url_for('admin'))
    db = get_db()
    db.execute('INSERT INTO announcements (content, admin_username) VALUES (?, ?)', (content, admin_username))
    db.commit()
    socketio.emit('new_announcement', {'content': content, 'admin': admin_username})
    flash('Thông báo đã được gửi thành công!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('Bạn không thể xóa chính tài khoản của mình.', 'error')
        return redirect(url_for('admin'))
    try:
        db = get_db()
        user_to_delete = db.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
        if user_to_delete:
            db.execute('DELETE FROM users WHERE id = ?', (user_id,))
            db.execute('DELETE FROM chat WHERE username = ?', (user_to_delete['username'],))
            db.commit()
            flash(f"Đã xóa thành công người dùng '{user_to_delete['username']}'.", 'success')
        else:
            flash('Không tìm thấy người dùng để xóa.', 'error')
    except sqlite3.Error as e:
        flash(f'Lỗi cơ sở dữ liệu khi xóa người dùng: {e}', 'error')
    return redirect(url_for('admin'))

# --- LOGIC BOT (Giữ nguyên theo yêu cầu) ---
def remove_diacritics(text):
    nfkd_form = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def extract_city_from_prompt(prompt):
    words = prompt.split()
    common_words = {'thời', 'tiết', 'nhiệt', 'độ', 'tại', 'ở', 'bây', 'giờ', 'là', 'bao', 'nhiêu', 'hôm', 'nay'}
    potential_cities = [word for word in words if word.istitle() and word.lower() not in common_words]
    if potential_cities:
        return " ".join(potential_cities)
    return None

def get_current_weather(city="Hanoi"):
    if not WEATHER_API_KEY: return "Lỗi: Chưa cấu hình API key cho dịch vụ thời tiết."
    city_no_diacritics = remove_diacritics(city)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city_no_diacritics}&appid={WEATHER_API_KEY}&units=metric&lang=vi"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        description, temp, city_name = data['weather'][0]['description'], data['main']['temp'], data['name']
        return f"Thời tiết tại {city} hiện tại: {temp}°C, {description}."
    except requests.exceptions.Timeout:
        return "Xin lỗi, yêu cầu xem thời tiết đã mất quá nhiều thời gian để xử lý."
    except Exception:
        return f"Chào bạn! Dường như mình chưa tìm được thông tin về nhiệt độ ở {city} hiện tại. Có lẽ hệ thống đang gặp vấn đề hoặc bạn có thể thử lại với tên thành phố khác nhé!"

def search_the_web(query):
    try:
        print(f"🔎 Bắt đầu tìm kiếm trên web cho: '{query}'")
        urls = list(search(query, num_results=3, lang='vi'))
        if not urls: return "Không tìm thấy kết quả nào trên mạng."
        content_snippets = []
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        for url in urls:
            try:
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                paragraphs = [p.get_text() for p in soup.find_all('p')]
                text = ' '.join(paragraphs[:5])
                content_snippets.append(text[:500])
            except requests.exceptions.Timeout:
                print(f"Lỗi timeout khi đọc URL {url}")
                continue
            except Exception as e:
                print(f"Lỗi khi đọc URL {url}: {e}")
                continue
        if not content_snippets: return "Không thể đọc nội dung từ các kết quả tìm thấy."
        print(f"✅ Đã trích xuất nội dung từ {len(content_snippets)} link.")
        return "\n\n--- Trích dẫn ---\n\n".join(content_snippets)
    except Exception as e:
        print(f"Lỗi nghiêm trọng trong quá trình tìm kiếm: {e}")
        return "Đã có lỗi xảy ra khi cố gắng tìm kiếm thông tin."

def get_ai_response(prompt):
    if not ai_model: return "Lỗi: Mô hình AI chưa được khởi tạo."
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            safety_settings = [{"category": c, "threshold": "BLOCK_NONE"} for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
            future = executor.submit(ai_model.generate_content, prompt, safety_settings=safety_settings)
            response = future.result(timeout=20)
        return response.text.replace('*', '').strip()
    except TimeoutError:
        return "Xin lỗi, yêu cầu của tôi đến AI đã mất quá nhiều thời gian để xử lý."
    except Exception as e:
        return f"Xin lỗi, tôi gặp lỗi khi xử lý yêu cầu của bạn: {e}"

# --- LOGIC SOCKET.IO ---
def _save_file(file_data, upload_folder, allowed_extensions_func):
    if not file_data: return None, None
    original_filename = file_data['filename']
    if not allowed_extensions_func(original_filename): return None, None
    new_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(original_filename)}"
    filepath = os.path.join(upload_folder, new_filename)
    try:
        with open(filepath, 'wb') as f: f.write(base64.b64decode(file_data['data'].split(',')[1]))
        return f"/{filepath.replace(os.path.sep, '/')}", original_filename
    except Exception: return None, None

def _create_and_emit_message(username, message, image_url=None, file_url=None, original_filename=None):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('INSERT INTO chat (username, message, image_path, file_path) VALUES (?, ?, ?, ?)',
                   (username, message, image_url, file_url))
    last_id = cursor.lastrowid
    db.commit()

    payload = None

    # Xử lý riêng cho BOT vì nó không có trong bảng USERS
    if username == 'Bot':
        # Tạo payload thủ công cho bot
        timestamp_str = datetime.now(timezone(timedelta(hours=7))).strftime('%H:%M, %d/%m/%Y')
        bot_avatar = '/static/image/bot_avatar.png'  # Avatar riêng cho bot
        payload = {
            'user': 'Bot',
            'message': message,
            'image': image_url,
            'file_info': {'url': file_url, 'name': original_filename} if file_url else None,
            'timestamp': timestamp_str,
            'avatar_path': '/static/image/uploads/bot.jpg'
        }
    else:
        # Lấy thông tin đầy đủ của tin nhắn từ người dùng thật
        new_message = db.execute('''
            SELECT c.*, u.avatar_path
            FROM chat c JOIN users u ON c.username = u.username
            WHERE c.id = ?
        ''', (last_id,)).fetchone()

        if new_message:
            local_tz = timezone(timedelta(hours=7))
            utc_dt_naive = datetime.strptime(new_message['timestamp'], '%Y-%m-%d %H:%M:%S')
            utc_dt_aware = utc_dt_naive.replace(tzinfo=timezone.utc)
            local_dt = utc_dt_aware.astimezone(local_tz)
            timestamp_str = local_dt.strftime('%H:%M, %d/%m/%Y')
            
            payload = {
                'user': new_message['username'],
                'message': new_message['message'],
                'image': new_message['image_path'],
                'file_info': {'url': new_message['file_path'], 'name': original_filename} if new_message['file_path'] else None,
                'timestamp': timestamp_str,
                'avatar_path': new_message['avatar_path']
            }

    # Chỉ emit khi có payload hợp lệ
    if payload:
        socketio.emit('receive_message', payload)

@socketio.on('send_message')
@login_required
def handle_send_message(data):
    username = session.get('username')
    message = data.get('message', '').strip()
    image_url, _ = _save_file(data.get('image'), app.config['UPLOAD_IMAGE_FOLDER'], allowed_image)
    file_url, original_filename = _save_file(data.get('file'), app.config['UPLOAD_FILE_FOLDER'], allowed_file)

    if message or image_url or file_url:
        _create_and_emit_message(username, message, image_url, file_url, original_filename)

    if message.lower().startswith('@bot'):
        prompt = message[4:].strip()
        if not prompt:
            _create_and_emit_message('Bot', "Bạn muốn hỏi tôi điều gì?")
            return

        socketio.emit('receive_message', {'user': 'Bot', 'message': 'Đang phân tích yêu cầu...', 'timestamp': datetime.now(timezone(timedelta(hours=7))).strftime('%H:%M, %d/%m/%Y'), 'avatar_path': '/static/image/uploads/bot.jpg'})
        
        history = session.get('bot_history', [])
        
        intent_analysis_prompt = f"""Phân tích câu hỏi cuối cùng của người dùng để chọn một công cụ: SEARCH, WEATHER, hoặc CONVERSE.
        - Dùng SEARCH cho các câu hỏi về sự thật, con người, địa điểm, định nghĩa.
        - Dùng WEATHER cho các câu hỏi về thời tiết.
        - Dùng CONVERSE cho các cuộc trò chuyện, chào hỏi, ý kiến.
        Lịch sử trò chuyện: {[turn['role'] + ': ' + turn['content'] for turn in history]}
        Câu hỏi cuối cùng của người dùng: "{prompt}"
        Công cụ nào là phù hợp nhất? Chỉ trả lời bằng một từ: SEARCH, WEATHER, hoặc CONVERSE."""
        intent = get_ai_response(intent_analysis_prompt).strip().upper()

        bot_response_text = ""
        contextual_prompt = "\n".join([f"{turn['role']}: {turn['content']}" for turn in history]) + f"\nUser: {prompt}"

        if "WEATHER" in intent:
            city = extract_city_from_prompt(prompt) or "Hà Nội" or "Hưng Yên" or "Đà Nẵng"
            bot_response_text = get_current_weather(city)
        elif "SEARCH" in intent:
            query_generation_prompt = f"""Dựa trên lịch sử và câu hỏi cuối, tạo một cụm từ tìm kiếm Google ngắn gọn. Chỉ trả về cụm từ tìm kiếm. Lịch sử: {[turn['role'] + ': ' + turn['content'] for turn in history]}. Câu hỏi cuối cùng: "{prompt}". Cụm từ tìm kiếm nên là:"""
            search_query = get_ai_response(query_generation_prompt)
            socketio.emit('receive_message', {'user': 'Bot', 'message': f"Đang tìm kiếm: '{search_query}'...", 'timestamp': datetime.now(timezone(timedelta(hours=7))).strftime('%H:%M, %d/%m/%Y'), 'avatar_path': '/static/image/uploads/bot.jpg'})
            search_results = search_the_web(search_query)
            final_prompt = f"""Dựa vào thông tin tìm kiếm được để trả lời câu hỏi gốc của người dùng. Thông tin: {search_results}. Câu hỏi: "{prompt}"."""
            bot_response_text = get_ai_response(final_prompt)
        else:
            bot_response_text = get_ai_response(contextual_prompt)
        
        history.append({'role': 'User', 'content': prompt})
        history.append({'role': 'Bot', 'content': bot_response_text})
        if len(history) > 10: history = history[-10:]
        session['bot_history'] = history

        _create_and_emit_message('Bot', bot_response_text)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')