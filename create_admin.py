import sqlite3

DB_NAME = 'chat.db'

def make_admin():
    try:
        username_to_promote = input("Nhập username bạn muốn nâng cấp thành admin: ")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE username=?", (username_to_promote,))
        user = cursor.fetchone()

        if user:
            cursor.execute("UPDATE users SET role = ? WHERE username = ?", ('quanly', username_to_promote))
            conn.commit()
            print(f"✅ Đã nâng cấp thành công người dùng '{username_to_promote}' thành admin.")
        else:
            print(f"❌ Không tìm thấy người dùng có username là '{username_to_promote}'.")
        
        conn.close()

    except sqlite3.Error as e:
        print(f"Lỗi cơ sở dữ liệu: {e}")

if __name__ == '__main__':
    make_admin()