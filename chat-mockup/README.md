# Chat Mockup Studio

App dựng khung chat (file `public/index.html`) kèm hệ thống **đăng ký → chờ duyệt → đăng nhập**
chạy trên Cloudflare Pages (`functions/_middleware.js`). Người chưa đăng nhập hoặc chưa được duyệt
không tải được app – việc chặn diễn ra trên máy chủ.

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `public/index.html` | App (một file, chạy hoàn toàn trong trình duyệt) |
| `functions/_middleware.js` | Đăng ký, đăng nhập, trang duyệt nhân viên, chặn truy cập |

Trang có sẵn: `/register` (đăng ký) · `/login` (đăng nhập) · `/admin` (duyệt, chỉ quản trị viên) · `/logout`.

## Cài đặt lần đầu trên Cloudflare (khoảng 10 phút)

1. **Tạo nơi lưu tài khoản (KV):** Storage & databases → **KV** → Create → đặt tên `chat-studio-users`.
2. **Tạo project nối với GitHub:** Compute → Workers & Pages → Create → **Pages** →
   **Import an existing Git repository** → chọn repo `value-alpha-btc-bot` rồi điền:
   - Production branch: `chat-mockup-studio`
   - Framework preset: **None** · Build command: *(để trống)* · Build output directory: `public`
   - Root directory (trong *Advanced*): `chat-mockup`
   - Bấm **Save and Deploy**.
3. **Gắn KV:** project → Settings → **Bindings** → Add → *KV namespace* → Variable name **`USERS`** → chọn `chat-studio-users`.
4. **Tài khoản quản trị:** project → Settings → **Variables and secrets** → Add:
   - `ADMIN_EMAIL` (Text) = email của bạn
   - `ADMIN_PASSWORD` (**Secret**) = mật khẩu quản trị, ít nhất 10 ký tự
5. **Deploy lại để nhận cấu hình:** tab Deployments → bản mới nhất → **Retry deployment**.
6. Mở `https://<tên-project>.pages.dev` → đăng nhập bằng `ADMIN_EMAIL` / `ADMIN_PASSWORD` → vào trang **Duyệt nhân viên**.

> Không bật Cloudflare Access (Zero Trust) cho project này – nó sẽ chặn luôn trang đăng ký.

## Dùng hằng ngày

- Nhân viên mở link → **Đăng ký** (họ tên, email, mật khẩu) → thấy "Đang chờ duyệt".
- Bạn đăng nhập → `/admin` → **✅ Duyệt** / **❌ Từ chối**. Người đã duyệt có nút **⛔ Thu hồi**; **🗑 Xoá** để xoá hẳn.
- Thu hồi / xoá có hiệu lực ở lần tải trang kế tiếp của người đó (chậm tối đa khoảng 1 phút).
- Phiên đăng nhập kéo dài 7 ngày.

## Cập nhật app

Mỗi lần có commit mới trên nhánh `chat-mockup-studio`, Cloudflare tự deploy lại. Danh sách tài khoản giữ nguyên.

## Bảo mật

- Mật khẩu được băm PBKDF2-SHA256 (100.000 vòng, salt riêng); không lưu mật khẩu gốc.
- Cookie phiên `HttpOnly; Secure; SameSite=Lax`; form từ trang khác bị từ chối.
- Giới hạn: 8 lần đăng nhập sai / 15 phút mỗi email; 5 lần đăng ký / giờ mỗi IP.

## Chạy thử trên máy

```bash
cd chat-mockup
npx wrangler pages dev public --kv USERS \
  --binding ADMIN_EMAIL=admin@example.com --binding ADMIN_PASSWORD=matkhau-thu-nghiem
```
