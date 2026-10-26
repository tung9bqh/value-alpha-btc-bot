# Value Alpha Crypto – BTC Daily Strategy Bot

Tự động đăng **chiến lược giao dịch BTC hằng ngày (tiếng Anh)** lên kênh Telegram
*Value Alpha Crypto* lúc **08:30 sáng (giờ Việt Nam)**, chạy miễn phí bằng GitHub Actions.

## Nội dung mỗi bài
- Giá hiện tại, % thay đổi 24h, xu hướng (Bullish / Bearish / Range)
- EMA20/50/200, RSI (D1 & 4H), ATR, biên độ 7 ngày
- Pivot, kháng cự R1/R2, hỗ trợ S1/S2
- Kịch bản chính (vùng vào lệnh, Stop-loss, TP1/TP2, R:R) + kịch bản thay thế
- Quản lý vốn + disclaimer “Not financial advice”

Dữ liệu: Binance (`data-api.binance.vision`), dự phòng Coinbase. Không cần API key.

## Không ảnh hưởng cộng đồng tiếng Việt
- Bot **chỉ** gửi tới đúng một chat: secret `TELEGRAM_CHAT_ID_EN` (kênh tiếng Anh).
- Script chỉ gọi `sendMessage` – **không** gọi `getUpdates` / `setWebhook`, nên nếu bạn
  dùng chung bot token với bot đang phục vụ nhóm tiếng Việt, bot cũ vẫn chạy bình thường.
- Khuyến nghị an toàn nhất: tạo **bot riêng** qua @BotFather cho kênh tiếng Anh.

## Cài đặt (5 phút)
1. **Thêm bot vào kênh tiếng Anh** với quyền Admin → *Post messages*.
2. **Lấy chat ID của kênh**: kênh public dùng `@username` (vd. `@ValueAlphaCrypto`);
   kênh private dùng ID dạng `-100xxxxxxxxxx`.
3. **Đưa thư mục này lên một GitHub repo** (nên để Private).
4. Repo → *Settings → Secrets and variables → Actions → New repository secret*:
   - `TELEGRAM_BOT_TOKEN` – token của bot (bắt buộc)
   - `TELEGRAM_CHAT_ID_EN` – không bắt buộc; mặc định đăng vào `@valuealphacrypto` (kênh tiếng Anh)
5. **Chạy thử**: tab *Actions → BTC Daily Strategy (EN channel) → Run workflow*
   - `dry_run` = ✅: chỉ in bài viết trong log (không đăng)
   - `dry_run` = ☐: đăng thật ngay lập tức lên kênh

Từ đó trở đi, workflow tự chạy mỗi ngày.

## Ghi chú
- Lịch GitHub thường chạy trễ vài phút, nên job khởi động lúc 08:10 và script tự **đợi đến đúng 08:30**
  mới lấy dữ liệu và đăng. Nếu GitHub trễ quá 20 phút thì bài sẽ đăng ngay khi job chạy.
- GitHub tự tắt lịch của repo **không có commit nào trong 60 ngày** – vào tab Actions bấm *Enable* lại,
  hoặc thỉnh thoảng commit một thay đổi nhỏ.
- Đổi múi giờ: biến môi trường `POST_TZ_OFFSET_HOURS` (mặc định `7`). Đổi tên kênh: `CHANNEL_NAME`.
- Chạy trên máy: `python btc_daily_bot.py --dry-run`
