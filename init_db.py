import sqlite3

conn = sqlite3.connect('chat.db')
cursor = conn.cursor()

# Bảng người dùng
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL
)
''')

# Bảng chat
cursor.execute('''
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    message TEXT,
    image_path TEXT,
    file_path TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Bảng thông báo (quan trọng)
cursor.execute('''
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    admin_username TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()
conn.close()
print("✅ Cơ sở dữ liệu đã được tạo với bảng announcements.")