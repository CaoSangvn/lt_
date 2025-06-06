from ftplib import FTP
import os

def upload_file_ftp(filepath):
    try:
        # Kết nối đến FTP server
        ftp = FTP()
        ftp.connect('localhost', 21, timeout=10)  # Cổng mặc định là 21
        ftp.login('user', 'pass')  # Thay bằng user/pass thật

        # Lấy tên file từ đường dẫn
        filename = os.path.basename(filepath)

        # Mở và upload file
        with open(filepath, 'rb') as f:
            ftp.storbinary(f'STOR {filename}', f)

        ftp.quit()
        print(f"✅ Đã upload thành công: {filename}")
        
    except Exception as e:
        print(f"❌ Lỗi khi upload file qua FTP: {e}")
