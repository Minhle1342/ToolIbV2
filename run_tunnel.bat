@echo off
echo Running Cloudflare Tunnel...
cloudflared tunnel --url https://localhost:5000 --no-tls-verify
pause
