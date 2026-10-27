# Value Alpha Crypto – BTC Daily Strategy Bot

Tự động đăng **kế hoạch giao dịch BTC hằng ngày (tiếng Anh)** lên kênh Telegram
*Value Alpha Crypto* lúc **08:30 sáng (giờ Việt Nam)**, chạy miễn phí bằng GitHub Actions.

## Nội dung mỗi bài
**Ảnh plan khung M15**: header BTCUSDT + kịch bản ưu tiên (LONG/SHORT), ngày, khung M15,
chart nến với EMA20/50/200, vùng chờ vào lệnh + mũi tên kịch bản, SL/TP1/TP2, giá hiện tại,
khung *Entry Conditions* (3 điều kiện) và cảnh báo *Don't FOMO*.

**Bài viết (tiếng Anh)**:
- `BTCUSDT UPDATE — <ngày>` và `PRIMARY BIAS: LONG/SHORT`
- `MULTI-TIMEFRAME ANALYSIS`: nhận định H4, H1, M30/M15 (cấu trúc đỉnh/đáy, EMA20/50/200, RSI)
- `KEY ZONES`: Primary (vùng hồi/điều chỉnh) + Breakdown/Breakout (chờ H1 đóng nến phá vỡ rồi retest)
- Mỗi setup có Entry (giữa vùng), **SL cố định 1.2%**, **TP1 = RR 1:1**, **TP2 = RR 1:1.5**
- `ALTCOIN WATCHLIST` và disclaimer

Dữ liệu: hợp đồng vĩnh cửu **BTCUSDT.P** trên **Bitget** (dự phòng: OKX `BTC-USDT-SWAP`).
Không cần API key. Trọng số quyết định LONG/SHORT: H4 40%, H1 30%, M30 17%, M15 13%.

Tuỳ chỉnh qua biến môi trường: `SL_PCT` (mặc định `1.2`), `ALTCOIN_WATCHLIST` (mặc định `ETH,SOL,SUI,AVAX,UNI`).

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
