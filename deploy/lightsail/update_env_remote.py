from pathlib import Path
p = Path('/opt/guardian-weather-watch/.env')
text = p.read_text(encoding='utf-8') if p.exists() else ''
updates = {'HF_NUM_THREADS':'2','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','HF_NUM_INTEROP':'1'}
lines = text.splitlines()
out = []
seen = set()
for line in lines:
    if '=' in line:
        k = line.split('=', 1)[0].strip()
        if k in updates:
            out.append(f'{k}={updates[k]}')
            seen.add(k)
        else:
            out.append(line)
    else:
        out.append(line)
for k, v in updates.items():
    if k not in seen:
        out.append(f'{k}={v}')
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
print('updated .env')