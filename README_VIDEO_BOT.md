# راهنمای راه‌اندازی Video Bot

این راهنما به شما کمک می‌کند که `Video_bot.py` را در محیط مجازی (virtual environment) خودش راه‌اندازی کنید.

## پیش‌نیازها

- Python 3.13 یا 3.12 (Python 3.14+ ممکن است با pydantic-core مشکل داشته باشد)
- pip (معمولاً با Python نصب می‌شود)
- Rust (برای کامپایل برخی پکیج‌ها - به صورت خودکار نصب می‌شود)
- ffmpeg (برای re-encoding ویدیوها - اختیاری)

## مراحل راه‌اندازی

### 1. ایجاد محیط مجازی و نصب وابستگی‌ها

```bash
# اجرای اسکریپت راه‌اندازی
chmod +x setup_video_bot.sh
./setup_video_bot.sh
```

یا به صورت دستی:

```bash
# ایجاد محیط مجازی
python3 -m venv venv_video_bot

# فعال‌سازی محیط مجازی
source venv_video_bot/bin/activate

# نصب وابستگی‌ها
pip install -r requirements.txt
```

### 2. تنظیم فایل .env

فایل `.env.example` را کپی کنید و به `.env` تغییر نام دهید:

```bash
cp .env.example .env
```

سپس فایل `.env` را باز کنید و مقادیر زیر را پر کنید:

```
ACCESS_TOKEN=your_instagram_graph_api_access_token
INSTAGRAM_ACCOUNT_ID=your_instagram_account_id
GEMINI_API_KEY=your_gemini_api_key
POST_INTERVAL_MINUTES=1
```

### 3. تنظیم Google Sheets Credentials

فایل `credentials.json` را از Google Cloud Console دریافت کنید و در پوشه پروژه قرار دهید.

### 4. بررسی Worksheet در Google Sheet

قبل از اجرای bot، می‌توانید لیست worksheet های موجود را ببینید:

```bash
source venv_video_bot/bin/activate
python list_worksheets.py
```

این اسکریپت تمام worksheet های موجود در Google Sheet را نمایش می‌دهد. اگر worksheet با نام "Yashans" پیدا نشود، bot به صورت خودکار از اولین worksheet استفاده می‌کند.

### 5. اجرای Bot

#### روش 1: استفاده از اسکریپت (پیشنهادی)

```bash
chmod +x run_video_bot.sh
./run_video_bot.sh
```

#### روش 2: اجرای دستی

```bash
# فعال‌سازی محیط مجازی
source venv_video_bot/bin/activate

# اجرای bot
python Video_bot.py

# غیرفعال‌سازی محیط مجازی (پس از اتمام)
deactivate
```

## ساختار فایل‌ها

- `Video_bot.py`: فایل اصلی bot
- `requirements.txt`: لیست وابستگی‌های Python
- `.env`: فایل تنظیمات (نباید در git commit شود)
- `credentials.json`: Google Service Account credentials
- `cookie-insta.json`: کوکی‌های اینستاگرام (برای دانلود ویدیو)

## نکات مهم

1. **محیط مجازی جداگانه**: این bot در محیط مجازی `venv_video_bot` اجرا می‌شود که جدا از `bot.py` است.

2. **فایل .env**: حتماً فایل `.env` را ایجاد کنید و مقادیر را پر کنید.

3. **Google Sheets**: باید Sheet را با ایمیل service account به اشتراک بگذارید:
   - `web-client-1@plenary-net-476220-c9.iam.gserviceaccount.com`
   - نقش: Editor

4. **ffmpeg**: برای re-encoding ویدیوها (اختیاری):
   ```bash
   brew install ffmpeg  # macOS
   ```

## عیب‌یابی

- **"Module not found"**: مطمئن شوید محیط مجازی فعال است (`source venv_video_bot/bin/activate`)
- **"credentials.json not found"**: فایل را در پوشه پروژه قرار دهید
- **".env not found"**: فایل `.env` را از `.env.example` ایجاد کنید
- **"Worksheet 'YaShans' not found"**: 
  - از `python list_worksheets.py` برای دیدن لیست worksheet ها استفاده کنید
  - bot به صورت خودکار از اولین worksheet استفاده می‌کند
  - یا نام worksheet را در `Video_bot.py` (خط 450) تغییر دهید
- **"pydantic-core build failed"**: 
  - از Python 3.13 یا 3.12 استفاده کنید (نه 3.14+)
  - محیط مجازی را دوباره بسازید: `rm -rf venv_video_bot && python3.13 -m venv venv_video_bot`

