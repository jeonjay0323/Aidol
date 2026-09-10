#!/usr/bin/env python3
"""out/ 안의 결과물을 한 장짜리 컨택트시트로 묶어 브라우저로 연다."""
import os, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DIRS = sys.argv[1:] or ["out"]

cols = []
for d in DIRS:
    path = os.path.join(BASE, d)
    files = sorted(f for f in os.listdir(path) if f.endswith(".png"))
    cells = "".join(
        f'<figure><img src="{d}/{f}"><figcaption>{f}</figcaption></figure>' for f in files
    )
    cols.append(f'<section><h2>{d} <small>({len(files)}장)</small></h2><div class="grid">{cells}</div></section>')

html = f"""<!doctype html><meta charset=utf-8><title>AIDOL 생성 결과</title>
<style>
body{{background:#141414;color:#eee;font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;padding:24px}}
h1{{font-size:18px;margin-bottom:20px}}
h2{{font-size:15px;color:#8ab;margin:28px 0 10px}}
small{{color:#777;font-weight:400}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}}
figure{{margin:0}}
img{{width:100%;border-radius:6px;display:block}}
figcaption{{font-size:11px;color:#888;margin-top:5px;text-align:center}}
</style>
<h1>AIDOL 생성 결과</h1>
{''.join(cols)}"""

out = os.path.join(BASE, "sheet.html")
open(out, "w").write(html)
subprocess.run(["open", out])
print(out)
