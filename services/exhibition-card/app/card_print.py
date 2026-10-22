"""
4×6 인쇄 카드(label.html)에 들어가는 값.
피그마 '루키즈_인쇄'(HxXQLteO8I3iDo9kqjUuqU)의 카드는 등급 · 영문 이름 · 한마디 · 스탯 하나를 보여 주는데
카드 DB 에는 이 값이 없다(등급만 stats.grade 로 정해 둘 수 있다). 카드 번호로 정해서 같은 카드는 몇 번을 뽑아도 같게 나오게 한다.
인쇄 화면에서 손으로 바꿀 수 있고, 주소 뒤에 ?grade= &en= &msg= &stat= 로 넘겨도 된다.
"""
import hashlib

GRADES = ["sss", "s", "a", "n"]
# 등급 비율 — 높은 등급일수록 드물게
WEIGHTS = [("sss", 10), ("s", 20), ("a", 30), ("n", 40)]
DEFAULT_MSG = "네가 웃으면\n나도 기분이 좋아.\n언제나 네 옆에 있을게!"   # 피그마 예시 문구

_CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi",
         "yu", "eu", "ui", "i"]
_JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t",
         "ng", "t", "t", "k", "t", "p", "t"]


def _seed(card_id):
    return int(hashlib.md5(card_id.encode()).hexdigest(), 16)


def grade_of(card_id):
    n = _seed(card_id) % 100
    for g, w in WEIGHTS:
        if n < w:
            return g
        n -= w
    return "n"


def stat_of(card_id):
    return 60 + (_seed(card_id) // 100) % 40


def romanize(name):
    """국어의 로마자 표기법을 글자 단위로만 (받침 연음 · 자음 동화는 하지 않는다).
    피그마 예시처럼 세 글자 한글 이름이면 성을 빼고 이름만 쓴다 (김유나 → yu na)."""
    hangul = [ch for ch in name if "가" <= ch <= "힣"]
    if len(hangul) == 3 and len(hangul) == len(name.strip()):
        name = name.strip()[1:]
    out, word = [], ""
    for ch in name:
        if "가" <= ch <= "힣":
            if word:
                out.append(word)
                word = ""
            i = ord(ch) - 0xAC00
            out.append(_CHO[i // 588] + _JUNG[(i % 588) // 28] + _JONG[i % 28])
        elif ch.strip():
            word += ch            # 영문 · 숫자는 그대로 이어 쓴다
        elif word:
            out.append(word)
            word = ""
    if word:
        out.append(word)
    return " ".join(out)


def values(card, query):
    """인쇄 카드에 들어갈 값. 주소의 값이 있으면 그것을 쓴다."""
    cid = card["card_id"]
    # 등급: 주소 > 발급할 때 정한 값(stats.grade) > 카드 번호
    grade = (query.get("grade") or (card.get("stats") or {}).get("grade") or "").lower()
    try:
        stat = max(0, min(100, int(query.get("stat", ""))))
    except ValueError:
        stat = stat_of(cid)
    return {
        "grade": grade if grade in GRADES else grade_of(cid),
        "en": query.get("en") or romanize(card["name"]),
        "msg": query.get("msg") or DEFAULT_MSG,
        "stat": stat,
    }
