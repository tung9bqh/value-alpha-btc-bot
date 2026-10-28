# Value Alpha Crypto – BTC Daily Strategy Bot

Tự động đăng **kế hoạch giao dịch BTC hằng ngày (tiếng Anh)** lên kênh Telegram
*Value Alpha Crypto* lúc **08:30 sáng (giờ Việt Nam)**, chạy miễn phí bằng GitHub Actions.

## Nội dung mỗi bài
**Ảnh plan khung M15**: header BTCUSDT + kịch bản ưu tiên (LONG/SHORT), ngày, khung M15,
chart nến với EMA20/50/200, vùng chờ vào lệnh + mũi tên kịch bản, SL/TP1/TP2, giá hiện tại,
khung *Entry Conditions* (3 điều kiện) và cảnh báo *Don't FOMO*.

**Bài viết (tiếng Anh)**:
- `BTCUSDT UPDATE — <ngày>` và `PRIMARY BIAS: LONG/SHORT`
- `MULTI-TIMEFRAME ANALYSIS`: 1 đoạn xâu chuỗi H4 → H1 → M30/M15 (cấu trúc đỉnh/đáy, EMA, RSI) + 1 dòng `Conclusion`
- `KEY ZONE`: 1 kịch bản Primary (vùng hồi/điều chỉnh) với Entry (giữa vùng), **SL cố định 1.2%**,
  **TP1 = RR 1:1**, **TP2 = RR 1:1.5**
- `Cancel Scenario`: khi nào huỷ kịch bản (H1 đóng nến phá cấu trúc, giá chạy tới TP1 trước khi vào vùng,
  hết ngày không chạm vùng)
- `ALTCOIN WATCHLIST`: 5 đồng ngẫu nhiên mỗi ngày từ ETH, SOL, XAUT, BNB, LTC, SUI, XRP, LINK, AVAX, DOT,
  NEAR, ADA, DOGE, UNI, ZEC (cùng một ngày luôn ra cùng 5 đồng)
- Disclaimer

Dữ liệu: hợp đồng vĩnh cửu **BTCUSDT.P** trên **Bitget** (dự phòng: OKX `BTC-USDT-SWAP`).
Không cần API key. Trọng số quyết định LONG/SHORT: H4 40%, H1 30%, M30 17%, M15 13%.

Tuỳ chỉnh qua biến môi trường: `SL_PCT` (mặc định `1.2`), `ALTCOIN_POOL` (danh sách coin để chọn ngẫu nhiên).

## Theo dõi plan & tổng kết (tự động)
- **Cảnh báo** (workflow *Plan alerts*): kiểm tra nến M15 **mỗi 10 phút** (cả ngày lẫn đêm) và
  **trả lời vào bài 8:30** khi: giá chạm Entry, TP1, TP2, SL, H1 đóng nến phá cấu trúc, hoặc giá chạy tới TP1
  trước khi vào vùng. Mỗi sự kiện chỉ báo 1 lần; tin cảnh báo ghi giờ xảy ra thực tế.
- **Tổng kết hằng ngày**: 8:30 sáng hôm sau, ngay trước plan mới, bot đăng kết quả plan hôm qua.
- **Thống kê tuần**: sáng thứ Hai, kèm tổng kết ngày, đăng track record tuần trước (số plan, thắng/thua,
  win rate, tổng R).
- **Cách tính kết quả**: 50% vị thế chốt ở TP1 (dời SL về Entry), 50% chốt ở TP2 → TP2 = +1.25R,
  TP1 rồi về Entry = +0.5R, SL = −1R. Plan có hiệu lực 24h; hết hạn mà còn lệnh thì tính theo giá đóng cửa.
  Nếu một nến M15 chạm cả SL và TP, tính SL trước (thận trọng).
- Lịch sử plan lưu ở nhánh `state` của repo (tự động, không cần chỉnh tay).

## Lịch kinh tế 12:00 trưa (tự động)
- Mỗi ngày lúc **12:00 (giờ Việt Nam)**, bot đọc lịch kinh tế của **ForexFactory** (feed xuất dữ liệu chính thức,
  cùng dữ liệu với forexfactory.com/calendar), chỉ lấy tin **USD** có mức ảnh hưởng **High (màu đỏ)** trong 24 giờ tới.
- Đăng ảnh *ECONOMIC CALENDAR TODAY* (giờ UTC, Forecast, Previous, tác động có thể có lên BTC, giải thích từng tin)
  kèm caption ghi giờ UTC và UTC+7.
- **Ngày không có tin đỏ thì không đăng gì.**
- Chạy thử: tab *Actions → Economic Calendar (EN channel) → Run workflow* (để tích `dry_run`).
- Font tiêu đề (Anton, Bebas Neue, Great Vibes) nằm trong `fonts/`, giấy phép SIL Open Font License.

## Call tín hiệu từ TradingView (M5)
Chỉ báo *EMA V2.1 Pro* trên TradingView gửi alert qua webhook tới một **Cloudflare Worker** (`tv-relay/`),
Worker đăng lên kênh và **trả lời TP1 / TP2 / SL vào đúng bài vào lệnh** (lưu `message_id` theo mã lệnh trong KV).
- Cài lần đầu: tạo tài khoản Cloudflare (miễn phí) → *My Profile → API Tokens → Create Token* → mẫu
  **Edit Cloudflare Workers**. Thêm vào *Settings → Secrets and variables → Actions* của repo:
  - `CLOUDFLARE_API_TOKEN` – token vừa tạo
  - `CLOUDFLARE_ACCOUNT_ID` – Account ID (trang *Workers & Pages*, cột bên phải)
  - `TV_WEBHOOK_SECRET` – chuỗi bí mật tự đặt, điền giống hệt vào ô *Webhook secret* của chỉ báo
- Tab *Actions → Deploy TradingView relay (Cloudflare) → Run workflow*. Trang *Summary* hiện **Webhook URL**
  (`https://tv-relay.<subdomain>.workers.dev`). Ô `test_chat_id` (vd. kênh test) để gửi thử 1 lệnh + 1 reply.
- TradingView: Settings chỉ báo → nhóm *Telegram* → tích **Webhook mode**, điền *Webhook secret* → tạo alert
  *Any alert() function call*, Webhook URL = URL ở trên. Mỗi cặp coin một alert.
- Token bot chỉ nằm trong Cloudflare (secret của Worker), không nằm trên TradingView.
- **Ảnh tín hiệu**: bài vào lệnh được đăng dạng ảnh (nến M5 từ Bitget, dự phòng Binance, Bybit, OKX, Hyperliquid, Kraken; EMA20/50/200; vùng SL/TP1/TP2)
  kèm nội dung lệnh làm caption. Ảnh được chụp bằng Cloudflare Browser Rendering: tạo token riêng
  (*Create Custom Token* → quyền **Account · Browser Run · Edit**; tên cũ: Browser Rendering) và lưu vào secret `CLOUDFLARE_BROWSER_TOKEN`,
  rồi chạy lại workflow. Thiếu secret này hoặc vẽ ảnh lỗi thì bài vẫn được đăng dạng chữ như cũ.
- **TP1 / TP2**: trả lời bằng ảnh chart tới thời điểm chạm TP (đánh dấu điểm chạm) kèm ROI và PnL của tín hiệu
  tính trên margin 2.500 USDT (biến `RESULT_MARGIN` trong `tv-relay/wrangler.toml`, không tính phí). **SL**: chỉ ghi `❌ HIT SL | <cặp>`.
- Code chỉ báo không lưu trong repo (repo public).

## Hẹn giờ đúng giờ bằng Cloudflare (`scheduler/`)
Lịch `schedule:` của GitHub Actions không đảm bảo đúng giờ (có ngày trễ hàng giờ hoặc bỏ qua), nên một
**Cloudflare Worker** (Cron Triggers, miễn phí) kích hoạt các workflow đúng giờ:
08:30 bài plan, 12:00 lịch kinh tế, mỗi 5 phút kiểm tra cảnh báo. Lịch GitHub vẫn giữ làm dự phòng;
bot chỉ đăng plan / lịch kinh tế **một lần mỗi ngày** nên không bị trùng.
- Cài: tạo token GitHub tại *Settings → Developer settings → Fine-grained tokens* (chỉ repo này,
  quyền **Actions: Read and write**), thêm vào secret repo `GH_DISPATCH_TOKEN`, rồi chạy
  *Actions → Deploy on-time scheduler (Cloudflare) → Run workflow*. Dùng chung `CLOUDFLARE_API_TOKEN`,
  `CLOUDFLARE_ACCOUNT_ID` với TradingView relay.
- Token GitHub chỉ lưu trong secret của repo và secret của Worker.

## Không ảnh hưởng cộng đồng tiếng Việt
- Bot **chỉ** gửi tới đúng một chat: secret `TELEGRAM_CHAT_ID_EN` (kênh tiếng Anh).
- Script chỉ gọi `sendMessage` – **không** gọi `getUpdates` / `setWebhook`, nên nếu bạn
  dùng chung bot token với bot đang phục vụ nhóm tiếng Việt, bot cũ vẫn chạy bình thường.
- Khuyến nghị an toàn nhất: tạo **bot riêng** qua @BotFather cho kênh tiếng Anh.

## Cài đặt (5 phút)
1. **Thêm bot vào kênh tiếng Anh** với quyền Admin → *Post messages*.
2. **Lấy chat ID của kênh**: kênh public dùng `@username` (vd. `@ValueAlphaCrypto`);
   kênh private dùng ID dạng `-100xxxxxxxxxx`.
3. **Đưa thư mục này lên một GitHub repo**.
4. Repo → *Settings → Secrets and variables → Actions → New repository secret*:
   - `TELEGRAM_BOT_TOKEN` – token của bot (bắt buộc)
   - `TELEGRAM_CHAT_ID_EN` – không bắt buộc; mặc định đăng vào `@valuealphacrypto` (kênh tiếng Anh)
5. **Chạy thử**: tab *Actions → BTC Daily Strategy (EN channel) → Run workflow*
   - `dry_run` = ✅: chỉ xem trước (bài viết trong log, ảnh chart ở mục *Artifacts* cuối trang Summary)
   - `dry_run` = ☐: đăng thật ngay lập tức lên kênh

Từ đó trở đi, workflow tự chạy mỗi ngày.

## Ghi chú
- Lịch dự phòng của GitHub khởi động lúc 08:10 và script tự **đợi đến đúng 08:30**; nếu bài đã được đăng
  (qua Cloudflare hoặc lượt trước) thì lượt chạy muộn sẽ tự bỏ qua.
- Repo **public**: GitHub Actions miễn phí không giới hạn phút. Token bot nằm trong *Secrets* nên không bị lộ.
- Với repo public, GitHub tự tắt lịch chạy nếu repo **không có hoạt động trong 60 ngày** (GitHub sẽ gửi email
  báo trước). Nếu nhận email đó hoặc thấy bot ngừng đăng: vào tab *Actions*, chọn workflow và bấm *Enable*.
- Đổi múi giờ: biến môi trường `POST_TZ_OFFSET_HOURS` (mặc định `7`). Đổi tên kênh: `CHANNEL_NAME`.
- Đăng ngay một bài: tab *Actions → Post NOW to EN channel → Run workflow*
- Chạy trên máy: `pip install matplotlib && python btc_daily_bot.py --dry-run` (ảnh lưu ở `btc_plan.png`)
