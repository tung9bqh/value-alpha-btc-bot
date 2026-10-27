# Value Alpha Crypto – BTC Daily Strategy Bot

Tự động đăng **kế hoạch giao dịch BTC hằng ngày (tiếng Anh)** lên kênh Telegram
*Value Alpha Crypto* lúc **08:30 sáng (giờ Việt Nam)**, chạy miễn phí bằng GitHub Actions.

## Nội dung mỗi bài
- **Ảnh chart 4 khung M15 / M30 / H1 / H4** (nến, EMA20/50) có vẽ sẵn vùng Entry, SL, TP1, TP2
- Xu hướng + RSI của từng khung
- Đoạn nhận định tự động từ phân tích đa khung
- Kết luận rõ ràng **TODAY: LONG hoặc SHORT** kèm độ tin cậy (High / Medium / Low)
- Entry, SL, TP1/TP2 (kèm R:R), điều kiện vô hiệu, quản lý vốn, disclaimer

Dữ liệu: hợp đồng vĩnh cửu **BTCUSDT.P** trên **Bitget** (dự phòng: OKX `BTC-USDT-SWAP`).
Không cần API key. Trọng số quyết định: H4 40%, H1 30%, M30 17%, M15 13%.

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
   - `dry_run` = ✅: chỉ xem trước (bài viết trong log, ảnh chart ở mục *Artifacts* cuối trang Summary)
   - `dry_run` = ☐: đăng thật ngay lập tức lên kênh

Từ đó trở đi, workflow tự chạy mỗi ngày.

## Ghi chú
- Lịch GitHub thường chạy trễ vài phút, nên job khởi động lúc 08:10 và script tự **đợi đến đúng 08:30**
  mới lấy dữ liệu và đăng. Nếu GitHub trễ quá 20 phút thì bài sẽ đăng ngay khi job chạy.
- GitHub tự tắt lịch của repo **không có commit nào trong 60 ngày** – vào tab Actions bấm *Enable* lại,
  hoặc thỉnh thoảng commit một thay đổi nhỏ.
- Đổi múi giờ: biến môi trường `POST_TZ_OFFSET_HOURS` (mặc định `7`). Đổi tên kênh: `CHANNEL_NAME`.
- Đăng ngay một bài: tab *Actions → Post NOW to EN channel → Run workflow*
- Chạy trên máy: `pip install matplotlib && python btc_daily_bot.py --dry-run` (ảnh lưu ở `btc_plan.png`)
