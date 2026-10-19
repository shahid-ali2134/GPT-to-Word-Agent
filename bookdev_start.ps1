# Start "Nexus": the WhatsApp webhook plus a cloudflared tunnel to it.
# Prints the URL to paste into Twilio's WhatsApp sandbox settings
# ("When a message comes in", method POST). The quick-tunnel URL changes each
# time this script runs, so paste it again after every restart.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = Join-Path $root "bookdev"
New-Item -ItemType Directory -Force $dir | Out-Null

$hook = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if (-not $hook) {
    Start-Process -WindowStyle Hidden -WorkingDirectory $root python -ArgumentList "bookdev_webhook.py" `
        -RedirectStandardOutput (Join-Path $dir "webhook.out.log") -RedirectStandardError (Join-Path $dir "webhook.log")
}

$log = Join-Path $dir "tunnel.log"
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
if (Test-Path $log) { Remove-Item $log -Force }
Start-Process -WindowStyle Hidden "C:\Program Files (x86)\cloudflared\cloudflared.exe" `
    -ArgumentList "tunnel --url http://127.0.0.1:8787 --logfile `"$log`""

for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
        $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
        if ($m) {
            $url = $m.Matches[0].Value + "/whatsapp"
            Set-Content -Path (Join-Path $dir "public_url.txt") -Value $url -Encoding utf8
            "BOOKDEV_URL: $url"
            exit 0
        }
    }
}
"TUNNEL_FAILED: see $log"
