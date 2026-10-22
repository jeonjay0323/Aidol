#!/usr/bin/env python3
"""
4×6 인쇄 카드의 고정 레이어를 크롬으로 뽑는다 — app/card_png.py 가 이 위에 사진 · 글자 · QR 만 얹는다.
  make_print_layers.py [서버 주소] [카드ID]
  make_print_layers.py http://localhost:8800 G6CNSAAA

label.html 을 ?layer=base / over 로 열어 등급마다 두 장씩 static/print/<등급>/ 에 저장한다.
  base.png  사진 · 바뀌는 글자를 뺀 바닥
  over.png  사진 위에 올라가는 프레임 · 테두리 · 등급 (투명 배경)
피그마 디자인을 고치면 label.html 을 고치고 이 스크립트를 다시 돌린다. 카드ID 는 아무 카드나 된다(사진 · 글자는 빠진다).
"""
import subprocess
import sys
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "print"


def shot(url, path):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--default-background-color=00000000",
                    "--virtual-time-budget=8000", "--window-size=1181,1748",
                    f"--screenshot={path}", url], check=True, capture_output=True)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8800"
    card = sys.argv[2] if len(sys.argv) > 2 else "G6CNSAAA"
    for g in ["sss", "s", "a", "n"]:
        for layer in ["base", "over"]:
            path = OUT / g / f"{layer}.png"
            shot(f"{base}/label/{card}?grade={g}&layer={layer}", path)
            print(path.relative_to(OUT.parent.parent.parent))


if __name__ == "__main__":
    main()
