#!/usr/bin/env python3
"""레퍼런스 워터마크 제거용 전처리.

워터마크가 거의 항상 하단 밴드(小红书 ID, rednote ID, Dispatch 로고 등)에 몰려 있어서
아래쪽 일정 비율을 잘라낸 사본을 만든다. 프롬프트로 "무시하라"고 여섯 번 시도했지만
모두 뚫렸기 때문에 이미지 자체에서 없애는 쪽이 확실하다.

    python3 prep_refs.py            # ~/Desktop/*_boy|_girl → ~/Desktop/aidol-generator/refs_clean/
    python3 prep_refs.py --crop 0.14
"""
import os, shutil, subprocess, sys

DESKTOP = "/Users/jeonjei/Desktop"
BASE = os.path.dirname(os.path.abspath(__file__))
CLEAN = os.path.join(BASE, "refs_clean")
SRC_DIRS = ["face_boy", "face_girl", "pose_boy", "pose_girl",
            "outfit_boy", "outfit_girl", "cosplay_girl"]
EXTS = (".png", ".jpg", ".jpeg", ".webp")
CROP_RATIO = 0.10       # 하단에서 잘라낼 비율


def main():
    ratio = CROP_RATIO
    if "--crop" in sys.argv:
        ratio = float(sys.argv[sys.argv.index("--crop") + 1])

    from PIL import Image

    total = 0
    for d in SRC_DIRS:
        src = os.path.join(DESKTOP, d)
        if not os.path.isdir(src):
            print(f"  건너뜀 — {d} 없음")
            continue
        dst = os.path.join(CLEAN, d)
        os.makedirs(dst, exist_ok=True)
        n = 0
        for f in sorted(os.listdir(src)):
            if not f.lower().endswith(EXTS):
                continue
            sp = os.path.join(src, f)
            dp = os.path.join(dst, os.path.splitext(f)[0] + ".png")
            try:
                im = Image.open(sp).convert("RGB")
            except Exception as e:
                print(f"    실패 {f}: {e}")
                continue
            w, h = im.size
            im.crop((0, 0, w, int(h * (1 - ratio)))).save(dp)
            n += 1
        print(f"  {d}: {n}장")
        total += n
    print(f"\n완료 — {total}장 → {CLEAN}  (하단 {ratio:.0%} 제거)")


if __name__ == "__main__":
    main()
