#!/usr/bin/env bash
set -e
# TOKEN_B64 should be set via environment variable or AWS Secrets Manager
# Replace with: export TOKEN_B64="<your-base64-encoded-token>"
TOKEN_B64="${HF_TOKEN_B64:-YOUR_BASE64_TOKEN_HERE}"
TOKEN=$(printf '%s' "$TOKEN_B64" | base64 -d)
export TOKEN
python3 - <<'PY'
from pathlib import Path
import os
p = Path('/opt/guardian-weather-watch/.env')
text = p.read_text(encoding='utf-8') if p.exists() else ''
updates = {
    'HF_TOKEN': os.environ['TOKEN'],
    'HUGGINGFACE_HUB_TOKEN': os.environ['TOKEN'],
}
lines = text.splitlines()
out = []
seen = set()
for line in lines:
    if '=' in line:
        k = line.split('=', 1)[0].strip()
        if k in updates:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(line)
    else:
        out.append(line)
for k, v in updates.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
print('HF token updated in .env')
PY
sudo systemctl restart guardian-weather
sleep 10
sudo systemctl --no-pager --full status guardian-weather | sed -n '1,60p'