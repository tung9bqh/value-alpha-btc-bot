/**
 * Chat Mockup Studio – đăng ký / duyệt / đăng nhập (Cloudflare Pages Functions).
 *
 * Mọi request đều đi qua đây. Người chưa đăng nhập hoặc chưa được duyệt sẽ không
 * nhận được app (public/index.html) – việc chặn diễn ra trên máy chủ.
 *
 * Cấu hình trong Cloudflare (Settings của project Pages):
 *   - KV binding:        USERS           → một KV namespace bất kỳ
 *   - Biến môi trường:   ADMIN_EMAIL     → email của quản trị viên
 *   - Secret:            ADMIN_PASSWORD  → mật khẩu quản trị viên (≥ 10 ký tự)
 *
 * Dữ liệu trong KV:
 *   user:<email>  → {name,email,salt,hash,status,createdAt,decidedAt}
 *                   status: pending | approved | rejected | revoked
 *   sess:<id>     → {email,name,admin}   (tự hết hạn sau SESSION_DAYS)
 *   rl:<key>      → bộ đếm chống dò mật khẩu / spam đăng ký
 */

const SESSION_DAYS = 7;
const COOKIE = 'cms_sid';
const enc = new TextEncoder();

/* ---------------- tiện ích ---------------- */
const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
const randHex = n => { const a = new Uint8Array(n); crypto.getRandomValues(a); return hex(a); };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const normEmail = e => String(e || '').trim().toLowerCase();
const okEmail = e => /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$/.test(e) && e.length <= 200;

async function hashPassword(password, salt) {
  const key = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: enc.encode(salt), iterations: 100000 }, key, 256);
  return hex(bits);
}
function safeEqual(a, b) {
  a = String(a); b = String(b);
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}
function getCookie(req, name) {
  const m = (req.headers.get('Cookie') || '').match(new RegExp('(?:^|;\\s*)' + name + '=([^;]+)'));
  return m ? m[1] : null;
}
const cookieHeader = (value, maxAge) =>
  `${COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;

/** Chống dò: tối đa `limit` lần trong `ttl` giây cho mỗi key. Trả về true nếu đã vượt. */
async function rateLimited(env, key, limit, ttl) {
  const k = 'rl:' + key;
  const n = parseInt(await env.USERS.get(k)) || 0;
  if (n >= limit) return true;
  await env.USERS.put(k, String(n + 1), { expirationTtl: ttl });
  return false;
}
const clearRate = (env, key) => env.USERS.delete('rl:' + key);

/* ---------------- giao diện các trang đăng nhập ---------------- */
const CSS = `
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px;
background:#0f1014;color:#e8e8ee;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.card{width:100%;max-width:420px;background:#17181e;border:1px solid #2a2c35;border-radius:16px;padding:26px 24px}
.wide{max-width:900px}
h1{font-size:21px;margin:0 0 4px}.sub{color:#9a9cab;margin:0 0 18px;font-size:14px}
label{display:block;font-size:13px;color:#9a9cab;margin:12px 0 0}
input{width:100%;margin-top:5px;padding:11px 12px;border-radius:10px;border:1px solid #2a2c35;background:#101117;color:#e8e8ee;font:inherit}
input:focus{outline:2px solid #8b6cf0;outline-offset:-1px}
button,.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:10px 14px;border-radius:10px;border:1px solid #2a2c35;
background:#252733;color:#e8e8ee;font:inherit;cursor:pointer;text-decoration:none}
.primary{width:100%;margin-top:18px;background:#8b6cf0;border-color:#8b6cf0;color:#fff;font-weight:600}
.msg{padding:10px 12px;border-radius:10px;margin:0 0 14px;font-size:14px}
.err{background:#3a1d22;color:#ffb4b4;border:1px solid #5c2a31}.ok{background:#1c3324;color:#b6f0c6;border:1px solid #2c5a3a}
.info{background:#1d2840;color:#b9cdfa;border:1px solid #2c3e66}
.foot{margin-top:16px;font-size:14px;color:#9a9cab;text-align:center}a{color:#b49cff}
.logo{font-size:30px;margin-bottom:6px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 8px;border-top:1px solid #2a2c35;vertical-align:middle}
th{color:#9a9cab;font-weight:500;font-size:12.5px}
.tag{display:inline-block;padding:2px 9px;border-radius:20px;font-size:12px;font-weight:600}
.pending{background:#3d3418;color:#f6d77a}.approved{background:#1c3324;color:#8fe0a6}.rejected,.revoked{background:#3a1d22;color:#ffb4b4}
.acts{display:flex;gap:6px;flex-wrap:wrap}.acts form{margin:0}.acts button{padding:6px 10px;font-size:13px}
.g{background:#1f6b3a;border-color:#1f6b3a;color:#fff}.r{color:#ffb4b4}
h2{font-size:16px;margin:22px 0 6px}.top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.empty{color:#9a9cab;font-size:14px;padding:8px 0}
.scroll{overflow-x:auto}`;

function page(title, inner, { status = 200, headers = {}, wide = false } = {}) {
  const html = `<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)} · Chat Mockup Studio</title><meta name="robots" content="noindex"><style>${CSS}</style></head>
<body><main class="card${wide ? ' wide' : ''}">${inner}</main></body></html>`;
  return new Response(html, {
    status,
    headers: {
      'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY',
      'Referrer-Policy': 'same-origin', 'Content-Security-Policy': "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
      ...headers,
    },
  });
}
const redirect = (to, headers = {}) => new Response(null, { status: 303, headers: { Location: to, 'Cache-Control': 'no-store', ...headers } });
const msgBox = (kind, text) => (text ? `<div class="msg ${kind}">${text}</div>` : '');

function loginPage({ error = '', info = '', email = '' } = {}, status = 200) {
  return page('Đăng nhập', `
<div class="logo">💬</div><h1>Đăng nhập</h1><p class="sub">Chat Mockup Studio – chỉ tài khoản đã được duyệt mới dùng được.</p>
${msgBox('err', error)}${msgBox('info', info)}
<form method="post" action="/login">
  <label>Email<input type="email" name="email" value="${esc(email)}" required autocomplete="username" autofocus></label>
  <label>Mật khẩu<input type="password" name="password" required autocomplete="current-password"></label>
  <button class="primary" type="submit">Đăng nhập</button>
</form>
<p class="foot">Chưa có tài khoản? <a href="/register">Đăng ký</a></p>`, { status });
}

function registerPage({ error = '', name = '', email = '' } = {}, status = 200) {
  return page('Đăng ký', `
<div class="logo">📝</div><h1>Đăng ký sử dụng</h1><p class="sub">Điền thông tin, quản trị viên sẽ duyệt rồi bạn mới đăng nhập được.</p>
${msgBox('err', error)}
<form method="post" action="/register">
  <label>Họ và tên<input name="name" value="${esc(name)}" required maxlength="80" autocomplete="name" autofocus></label>
  <label>Email<input type="email" name="email" value="${esc(email)}" required maxlength="200" autocomplete="email"></label>
  <label>Mật khẩu (ít nhất 8 ký tự)<input type="password" name="password" required minlength="8" maxlength="200" autocomplete="new-password"></label>
  <label>Nhập lại mật khẩu<input type="password" name="password2" required minlength="8" maxlength="200" autocomplete="new-password"></label>
  <button class="primary" type="submit">Gửi đăng ký</button>
</form>
<p class="foot">Đã có tài khoản? <a href="/login">Đăng nhập</a></p>`, { status });
}

const STATUS_LABEL = { pending: 'Chờ duyệt', approved: 'Đã duyệt', rejected: 'Từ chối', revoked: 'Đã thu hồi' };
const fmtTime = t => (t ? new Date(t).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', hour12: false }) : '');

async function adminPage(env, flash = '') {
  const users = [];
  let cursor;
  do {
    const r = await env.USERS.list({ prefix: 'user:', cursor });
    for (const k of r.keys) users.push({ email: k.name.slice(5), ...(k.metadata || {}) });
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  users.sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
  const group = s => users.filter(u => (s === 'other' ? u.status === 'rejected' || u.status === 'revoked' : u.status === s));
  const btn = (email, action, label, cls = '') =>
    `<form method="post" action="/admin/action"><input type="hidden" name="email" value="${esc(email)}"><input type="hidden" name="action" value="${action}"><button class="${cls}" type="submit">${label}</button></form>`;
  const row = u => `<tr><td><b>${esc(u.name)}</b></td><td>${esc(u.email)}</td><td>${esc(fmtTime(u.createdAt))}</td>
<td><span class="tag ${esc(u.status)}">${esc(STATUS_LABEL[u.status] || u.status)}</span></td><td><div class="acts">${
    u.status === 'pending' ? btn(u.email, 'approve', '✅ Duyệt', 'g') + btn(u.email, 'reject', '❌ Từ chối', 'r')
    : u.status === 'approved' ? btn(u.email, 'revoke', '⛔ Thu hồi', 'r')
    : btn(u.email, 'approve', '✅ Duyệt lại', 'g')
  }${btn(u.email, 'delete', '🗑 Xoá', 'r')}</div></td></tr>`;
  const table = (list, empty) => list.length
    ? `<div class="scroll"><table><tr><th>Họ tên</th><th>Email</th><th>Đăng ký lúc</th><th>Trạng thái</th><th></th></tr>${list.map(row).join('')}</table></div>`
    : `<div class="empty">${empty}</div>`;
  const pend = group('pending');
  return page('Duyệt nhân viên', `
<div class="top"><div><h1>Duyệt nhân viên</h1><p class="sub" style="margin:0">${users.length} tài khoản · ${pend.length} đang chờ duyệt</p></div>
<div class="acts"><a class="btn" href="/">← Về app</a><a class="btn" href="/admin">↻ Tải lại</a><a class="btn" href="/logout">Đăng xuất</a></div></div>
<div style="height:12px"></div>${flash}
<h2>⏳ Đang chờ duyệt (${pend.length})</h2>${table(pend, 'Không có ai đang chờ.')}
<h2>✅ Đã duyệt (${group('approved').length})</h2>${table(group('approved'), 'Chưa duyệt ai.')}
<h2>🚫 Từ chối / thu hồi (${group('other').length})</h2>${table(group('other'), 'Không có.')}
<p class="foot" style="text-align:left">Thay đổi có hiệu lực ngay, có thể chậm tối đa khoảng 1 phút ở một số khu vực.</p>`, { wide: true });
}

/* ---------------- phiên đăng nhập ---------------- */
async function readSession(env, request) {
  const sid = getCookie(request, COOKIE);
  if (!sid || !/^[0-9a-f]{64}$/.test(sid)) return null;
  const s = await env.USERS.get('sess:' + sid, 'json');
  if (!s) return null;
  if (s.admin) return { ...s, sid };
  const user = await env.USERS.get('user:' + s.email, 'json');
  if (!user || user.status !== 'approved') return { ...s, sid, blocked: user ? user.status : 'deleted' };
  return { ...s, sid, name: user.name };
}
async function startSession(env, data) {
  const sid = randHex(32);
  await env.USERS.put('sess:' + sid, JSON.stringify(data), { expirationTtl: SESSION_DAYS * 86400 });
  return cookieHeader(sid, SESSION_DAYS * 86400);
}
const saveUser = (env, u) =>
  env.USERS.put('user:' + u.email, JSON.stringify(u), { metadata: { name: u.name, status: u.status, createdAt: u.createdAt } });

/* Chặn gửi form từ trang khác (CSRF) */
function sameOrigin(request) {
  const origin = request.headers.get('Origin');
  return !origin || origin === new URL(request.url).origin;
}

/* ---------------- xử lý chính ---------------- */
export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '') || '/';
  const method = request.method;

  if (!env.USERS) {
    return page('Chưa cấu hình', `<h1>⚙️ Chưa cấu hình xong</h1><p class="sub">Project chưa gắn KV namespace tên <b>USERS</b>. Vào Settings → Bindings của project Pages để thêm, rồi deploy lại.</p>`, { status: 500 });
  }
  const adminEmail = normEmail(env.ADMIN_EMAIL);
  const adminPass = String(env.ADMIN_PASSWORD || '');
  const adminReady = okEmail(adminEmail) && adminPass.length >= 10;

  if (method === 'POST' && !sameOrigin(request)) return page('Lỗi', '<h1>Yêu cầu không hợp lệ</h1>', { status: 403 });

  /* ----- Đăng ký ----- */
  if (path === '/register') {
    if (method === 'GET') return registerPage();
    if (method !== 'POST') return new Response('Method not allowed', { status: 405 });
    const f = await request.formData();
    const name = String(f.get('name') || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    const email = normEmail(f.get('email'));
    const pw = String(f.get('password') || ''), pw2 = String(f.get('password2') || '');
    const back = error => registerPage({ error, name, email }, 400);
    if (!name) return back('Vui lòng nhập họ tên.');
    if (!okEmail(email)) return back('Email không hợp lệ.');
    if (pw.length < 8 || pw.length > 200) return back('Mật khẩu cần từ 8 ký tự.');
    if (pw !== pw2) return back('Hai lần nhập mật khẩu không khớp.');
    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    if (await rateLimited(env, 'reg:' + ip, 5, 3600)) return back('Bạn gửi quá nhiều đăng ký. Thử lại sau 1 giờ.');
    if (email === adminEmail || await env.USERS.get('user:' + email)) return back('Email này đã được đăng ký. Hãy đăng nhập, hoặc liên hệ quản trị viên.');
    const salt = randHex(16);
    await saveUser(env, { name, email, salt, hash: await hashPassword(pw, salt), status: 'pending', createdAt: Date.now() });
    return page('Đã gửi đăng ký', `<div class="logo">⏳</div><h1>Đã gửi đăng ký</h1>
<div class="msg ok">Cảm ơn ${esc(name)}! Tài khoản <b>${esc(email)}</b> đang chờ quản trị viên duyệt.</div>
<p class="sub">Khi được duyệt, bạn đăng nhập bằng email và mật khẩu vừa đặt.</p><a class="btn primary" href="/login">Về trang đăng nhập</a>`);
  }

  /* ----- Đăng nhập ----- */
  if (path === '/login') {
    if (method === 'GET') {
      const s = await readSession(env, request);
      if (s && !s.blocked) return redirect('/');
      return loginPage({ info: adminReady ? '' : 'Quản trị viên chưa cấu hình ADMIN_EMAIL / ADMIN_PASSWORD.' });
    }
    if (method !== 'POST') return new Response('Method not allowed', { status: 405 });
    const f = await request.formData();
    const email = normEmail(f.get('email'));
    const pw = String(f.get('password') || '');
    if (!okEmail(email) || !pw) return loginPage({ error: 'Nhập email và mật khẩu.', email }, 400);
    if (await rateLimited(env, 'login:' + email, 8, 900)) return loginPage({ error: 'Sai quá nhiều lần. Thử lại sau 15 phút.', email }, 429);

    if (adminReady && email === adminEmail) {
      if (!safeEqual(pw, adminPass)) return loginPage({ error: 'Email hoặc mật khẩu không đúng.', email }, 401);
      await clearRate(env, 'login:' + email);
      return redirect('/admin', { 'Set-Cookie': await startSession(env, { email, name: 'Quản trị viên', admin: true }) });
    }
    const user = await env.USERS.get('user:' + email, 'json');
    if (!user || !safeEqual(await hashPassword(pw, user.salt), user.hash)) return loginPage({ error: 'Email hoặc mật khẩu không đúng.', email }, 401);
    await clearRate(env, 'login:' + email);
    if (user.status === 'pending') return loginPage({ info: '⏳ Tài khoản của bạn đang chờ quản trị viên duyệt. Hãy quay lại sau.', email }, 403);
    if (user.status !== 'approved') return loginPage({ error: 'Tài khoản này chưa được cấp quyền sử dụng. Liên hệ quản trị viên.', email }, 403);
    return redirect('/', { 'Set-Cookie': await startSession(env, { email, name: user.name }) });
  }

  /* ----- Đăng xuất ----- */
  if (path === '/logout') {
    const sid = getCookie(request, COOKIE);
    if (sid && /^[0-9a-f]{64}$/.test(sid)) await env.USERS.delete('sess:' + sid);
    return redirect('/login', { 'Set-Cookie': cookieHeader('', 0) });
  }

  /* ----- Từ đây trở đi: bắt buộc đã đăng nhập ----- */
  const session = await readSession(env, request);
  if (!session || session.blocked) {
    if (session) await env.USERS.delete('sess:' + session.sid);
    const isPage = method === 'GET' && (request.headers.get('Accept') || '').includes('text/html');
    return isPage ? redirect('/login', session ? { 'Set-Cookie': cookieHeader('', 0) } : {}) : new Response('Unauthorized', { status: 401 });
  }

  /* ----- Trang duyệt (chỉ quản trị viên) ----- */
  if (path === '/admin' || path === '/admin/action') {
    if (!session.admin) return page('Không có quyền', '<h1>Không có quyền</h1><p class="sub">Trang này chỉ dành cho quản trị viên.</p><a class="btn" href="/">← Về app</a>', { status: 403 });
    if (path === '/admin' && method === 'GET') return adminPage(env);
    if (path === '/admin/action' && method === 'POST') {
      const f = await request.formData();
      const email = normEmail(f.get('email')), action = String(f.get('action') || '');
      const user = await env.USERS.get('user:' + email, 'json');
      if (!user) return adminPage(env, msgBox('err', 'Không tìm thấy tài khoản.'));
      const label = `${esc(user.name)} (${esc(email)})`;
      if (action === 'delete') {   // bước 1: hỏi xác nhận
        return page('Xác nhận xoá', `<h1>Xoá tài khoản?</h1><p class="sub">${label} sẽ bị xoá hẳn và phải đăng ký lại nếu muốn dùng tiếp.</p>
<div class="acts"><form method="post" action="/admin/action"><input type="hidden" name="email" value="${esc(email)}"><input type="hidden" name="action" value="delete_yes"><button class="r" type="submit">🗑 Xoá hẳn</button></form><a class="btn" href="/admin">Huỷ</a></div>`);
      }
      if (action === 'delete_yes') {
        await env.USERS.delete('user:' + email);
        return adminPage(env, msgBox('ok', `Đã xoá ${label}.`));
      }
      const next = { approve: 'approved', reject: 'rejected', revoke: 'revoked' }[action];
      if (!next) return adminPage(env, msgBox('err', 'Thao tác không hợp lệ.'));
      user.status = next; user.decidedAt = Date.now();
      await saveUser(env, user);
      const done = { approved: 'Đã duyệt', rejected: 'Đã từ chối', revoked: 'Đã thu hồi quyền của' }[next];
      return adminPage(env, msgBox('ok', `${done} ${label}.`));
    }
    return new Response('Method not allowed', { status: 405 });
  }

  /* ----- App: chỉ trả về khi đã được duyệt; gắn thanh tài khoản nhỏ ----- */
  const res = await context.next();
  const headers = new Headers(res.headers);
  headers.set('Cache-Control', 'no-store');
  const out = new Response(res.body, { status: res.status, statusText: res.statusText, headers });
  if (!(headers.get('Content-Type') || '').includes('text/html')) return out;
  const bar = `<div id="cms-authbar" style="position:fixed;right:12px;bottom:12px;z-index:60;display:flex;gap:10px;align-items:center;
padding:7px 12px;border-radius:20px;background:rgba(23,24,30,.95);border:1px solid #2a2c35;color:#c9cbd6;
font:12.5px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.4)">
<span>👤 ${esc(session.name)}</span>${session.admin ? '<a href="/admin" style="color:#b49cff">Duyệt nhân viên</a>' : ''}
<a href="/logout" style="color:#b49cff">Đăng xuất</a></div>`;
  return new HTMLRewriter().on('body', { element(el) { el.append(bar, { html: true }); } }).transform(out);
}
