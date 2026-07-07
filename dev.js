const { spawn } = require('child_process');

const args = process.argv.slice(2);
const hasTunnel = args.includes('--tunnel') || args.includes('tunnel');

console.log('==========================================================');
console.log('🚀 Đang khởi chạy môi trường phát triển...');
console.log('==========================================================');

// 1. Khởi chạy Tailwind CSS watcher
console.log('[Tailwind] Đang chạy Tailwind CSS watcher...');
const tailwind = spawn('npx', ['tailwindcss', '-i', 'static/css/input.css', '-o', 'static/css/output.css', '--watch'], {
  stdio: 'inherit',
  shell: true
});

tailwind.on('error', (err) => {
  console.error('[Tailwind] Lỗi khi chạy Tailwind:', err);
});

tailwind.on('close', (code) => {
  console.log(`[Tailwind] Tiến trình Tailwind đã kết thúc với mã ${code}`);
  if (!hasTunnel) {
    process.exit(code);
  }
});

// 2. Khởi chạy Cloudflare Tunnel nếu có cờ --tunnel
if (hasTunnel) {
  console.log('[Cloudflare] Đang khởi chạy Cloudflare Tunnel...');
  const cloudflared = spawn('cloudflared', ['tunnel', '--config', 'config.yml', 'run'], {
    stdio: 'inherit',
    shell: true
  });

  cloudflared.on('error', (err) => {
    console.error('[Cloudflare] Lỗi khi chạy Cloudflared:', err);
    console.error('[Cloudflare] Vui lòng đảm bảo bạn đã cài đặt cloudflared và thêm vào biến môi trường PATH.');
  });

  cloudflared.on('close', (code) => {
    console.log(`[Cloudflare] Tiến trình Cloudflare đã kết thúc với mã ${code}`);
    process.exit(code);
  });
}
