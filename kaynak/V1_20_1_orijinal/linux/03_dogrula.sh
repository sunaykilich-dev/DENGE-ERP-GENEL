#!/usr/bin/env bash
set -Eeuo pipefail
printf 'Sunucu IP:\n'; ip -4 addr show | grep '10.10.50.16' || true
printf '\n.NET:\n'; dotnet --list-runtimes | grep -E 'Microsoft.AspNetCore.App 10|Microsoft.NETCore.App 10' || true
printf '\nServis:\n'; systemctl is-active dengeerp || true
printf '\nNginx:\n'; nginx -t
printf '\nPortlar:\n'; ss -lnt | grep -E ':5050|:5051' || true
printf '\nSaglik:\n'; curl -fsS --max-time 6 http://127.0.0.1:5051/api/health || true
printf '\nGuncel surum:\n'; readlink -f /opt/dengeerp/current || true
printf '\nSon servis kayitlari:\n'; journalctl -u dengeerp -n 12 --no-pager || true
