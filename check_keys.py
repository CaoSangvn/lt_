import os
from dotenv import load_dotenv

# Tải các biến từ tệp .env
load_dotenv()

print("--- Bắt đầu kiểm tra các biến môi trường ---")

gemini_key = os.getenv("GEMINI_API_KEY")
search_key = os.getenv("Google Search_API_KEY")
search_id = os.getenv("SEARCH_ENGINE_ID")

if gemini_key:
    print(f"✅ GEMINI_API_KEY:         Đã tìm thấy! (Giá trị bắt đầu bằng: {gemini_key[:8]}...)")
else:
    print("❌ GEMINI_API_KEY:         KHÔNG TÌM THẤY!")

if search_key:
    print(f"✅ Google Search_API_KEY:  Đã tìm thấy! (Giá trị bắt đầu bằng: {search_key[:8]}...)")
else:
    print("❌ Google Search_API_KEY:  KHÔNG TÌM THẤY!")

if search_id:
    print(f"✅ SEARCH_ENGINE_ID:       Đã tìm thấy! (Giá trị: {search_id})")
else:
    print("❌ SEARCH_ENGINE_ID:       KHÔNG TÌM THẤY!")

print("--- Kết thúc kiểm tra ---")

if not gemini_key or not search_key or not search_id:
    print("\n[GỢI Ý] Lỗi 'KHÔNG TÌM THẤY' thường do:")
    print("1. Tên biến trong tệp .env bị sai (ví dụ: có dấu cách, viết sai chữ).")
    print("2. Tệp .env không nằm cùng thư mục với tệp Python đang chạy.")