#!/usr/bin/env python3
"""더미 카드용 QR 생성. 현재 로컬 IP를 자동으로 잡아 카드가 가리킬 URL을 만든다."""
import socket
import subprocess
import sys
from pathlib import Path

import segno

CARD_ID = "AID7K2M9"
PORT = 8000
HERE = Path(__file__).parent


def local_ip():
    for iface in ("en0", "en1"):
        try:
            ip = subprocess.check_output(["ipconfig", "getifaddr", iface], text=True).strip()
            if ip:
                return ip
        except subprocess.CalledProcessError:
            continue
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else local_ip()
    url = f"http://{ip}:{PORT}/c/{CARD_ID}/"

    # error='m' = 15% 복원. 인쇄 후 긁힘/조명 반사에 견디는 최소선.
    qr = segno.make(url, error="m")
    qr.save(HERE / "qr.png", scale=20, border=2, dark="#2b1d14", light="#f2e6d2")

    (HERE / "url.txt").write_text(url + "\n")
    print(f"URL   : {url}")
    print(f"버전  : {qr.version}  (낮을수록 스캔 잘 됨)")
    print(f"저장  : {HERE / 'qr.png'}")


if __name__ == "__main__":
    main()
