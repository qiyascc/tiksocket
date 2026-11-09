from __future__ import annotations

HOME = "https://www.tiktok.com/"
LOGIN_URL = "https://www.tiktok.com/login/qrcode"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=webapp"
CONTENT_URL = "https://www.tiktok.com/tiktokstudio/content"
ACCOUNT_URL = "https://www.tiktok.com/passport/web/account/info/?aid=1459&app_name=tiktok_web"
INBOX_URLS = ("https://www.tiktok.com/messages?lang=en", "https://www.tiktok.com/messages?allow_label=true&lang=en&scene=business")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")
VIEWPORT = {"width": 1400, "height": 1000}
LOGIN_TTL = 300
MAX_VIDEO = 300 * 1024 * 1024
CAPTION_MAX = 2200
TITLE_MAX = 90
PHOTO_MAX = 35
DEFAULT_PORT = 8787
