#!/usr/bin/env python3
"""AI 아이돌 이미지 생성기 — normal (프리셋 기반)

기본:
    python3 normal.py                          # 전 프리셋 1장씩
    python3 normal.py cat wolf                 # 특정 프리셋만
    python3 normal.py --n 3                    # 프리셋당 3장
    python3 normal.py --gender both            # 남녀 동시 (m | f | both)
    python3 normal.py --mode editorial         # 화보컷 3:4 (기본 profile 4:3)
    python3 normal.py --seed 42                # 같은 결과 재현

레퍼런스 (~/Desktop 의 face_/pose_/outfit_ + _boy/_girl 폴더):
    python3 normal.py --refs face,pose,outfit  # 기본값
    python3 normal.py --refs face              # 얼굴만
    python3 normal.py --no-ref                 # 전부 끄기

프롬프트 직접 넣기:
    python3 normal.py -i                       # 실행 후 물어봄
    python3 normal.py --add "..."              # 프리셋 위에 덧붙임
    python3 normal.py --prompt "..."           # 프리셋 무시, 이것만 사용

결과 보기:
    python3 sheet.py out                       # 컨택트시트 생성 후 브라우저로 열기
"""

import base64, json, os, random, re, subprocess, sys, time, unicodedata, urllib.request, urllib.error

PROJECT = "aidol-505503"
MODEL = "gemini-2.5-flash-image"
LOCATIONS = ["us-central1", "us-east4", "us-west1", "us-west4",
             "europe-west1", "europe-west4"]
RETRIES = 3             # 실패 시 다른 지역으로 재시도할 횟수
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
INTERVAL = 8            # 요청 간격(초)

# ── 촬영 모드 ────────────────────────────────────────────────
# "profile"   = 카드용 정면 클로즈업. 4:3 가로컷
# "editorial" = 화보컷. 포즈·앵글 랜덤, 3:4 세로컷
SHOT_MODE = "profile"
ASPECT = {"profile": "4:3", "editorial": "3:4"}

# ── 고정 블록 ────────────────────────────────────────────────
# 얼굴 품질 베이스라인. 촬영 모드와 무관하게 항상 들어감.
GENDER = "m"        # "m" = 남자 아이돌, "f" = 여자 아이돌. --gender 로 전환

_SUBJECT = {
    "m": (
        "an extremely handsome Korean male K-pop idol, "
        "exactly 20 years old, boyish and youthful — never looks older than 22, "
        "no mature or manly features. "
        "Bare face, no makeup, no contouring, no nose highlight, smooth clear skin.",
        "He", "his",
    ),
    "f": (
        "an extremely beautiful Korean female K-pop idol, "
        "exactly 20 years old, fresh and youthful — never looks older than 22. "
        "Clean natural makeup only, no heavy contouring, no nose highlight, "
        "soft glossy lips, smooth clear skin.",
        "She", "her",
    ),
}

_SHARED_FACE = (
    # 얼굴 레퍼런스가 없을 때 — 골격을 텍스트로 규정
    "Large clear eyes, high nose bridge, short narrow chin, slim short V-line jaw — "
    "never wide, square or long. "
)
_SHARED_FACE_REF = (
    # 얼굴 레퍼런스가 있을 때 — 레퍼런스가 골격을 정하고, 하한선만 건다
    "Clear expressive eyes and a clean jawline. The jaw is never wide, square or heavy. "
)
_SHARED = (
    "High detail. Must NOT resemble any real celebrity. "
    "{They} wears no hat, no cap, no beanie and no headwear of any kind — "
    "{their} hair is fully visible. "
    "{They} wears no vest and no sleeveless outer layer. "
    "Jackets and shirts stay on both shoulders and never slide off to bare an arm. "
    "{Their_c} arms and chest stay covered — no bare upper arms, no exposed chest, "
    "at most the collarbone shows. "
    "Absolutely no text, no letters, no numbers, no watermark, no logo anywhere in the image."
)


def base_block(gender, face_ref=False):
    subject, they, their = _SUBJECT[gender]
    geom = _SHARED_FACE_REF if face_ref else _SHARED_FACE
    shared = _SHARED.format(They=they, their=their, Their_c=their.capitalize())
    return f"Photorealistic photo of {subject} {geom}{shared}"


BASE = base_block(GENDER)


# 모드별 카메라 / 배경 / 조명
FRAMING = {
    "profile": (
        "Framing: head and shoulders, straight-on eye-level angle, 85mm lens look, "
        "horizontal composition. "
        "The entire head must be fully visible with clear empty space above the hair — "
        "never crop the top of the head. "
        "Setting: inside an ordinary cozy bedroom, plain wall behind him, "
        "background softly blurred with shallow depth of field, no clutter, no posters, "
        "no text on the wall. "
        "Lighting: soft natural daylight from a window, even and gentle on the face. "
        "Premium idol profile photo."
    ),
    "editorial": (
        "This is a fashion magazine editorial photo — a styled photoshoot, not a casual snapshot. "
        "Framing: vertical composition, 50mm lens look. Cropped close, at the upper chest. "
        "The head occupies roughly 35 to 40 percent of the frame height and the subject "
        "fills most of the frame, with only a small amount of negative space to one side. "
        "The face is large and clearly readable — never a distant, small or full-length subject. "
        "His waist, legs and feet must be completely out of frame, "
        "and he must never be shown sitting on the floor with his legs visible. "
        "Setting: a bare white studio wall and floor, completely empty, no props, no furniture. "
        "Lighting: crisp directional daylight casting a soft defined shadow on the wall behind him. "
        "Slightly cool clean color grading, editorial retouching, sharp focus on the face. "
        "Confident model presence, magazine cover quality."
    ),
}

# profile 모드 배경 벽 색 — 헥스는 이미지에 글자로 박히므로 반드시 서술어로
BACKDROPS = [
    # Buppy 원본 배경은 #9BB3C4. 헥스를 프롬프트에 쓰면 이미지에 글자로 박혀서 서술어로 옮김.
    "muted dusty blue-grey",
    "muted dusty blue-grey",
    "muted dusty blue-grey",
    "soft slate blue",
    "pale cool grey",
]


# ── 화보 모드 전용: 포즈 / 앵글 ──────────────────────────────
POSES = [
    "leaning his shoulder and the back of his head against the wall, head tilted to one side, "
    "one hand raised to tug lightly at his collar",

    "leaning back against the wall with one hand pushing up through his hair, "
    "elbow raised high, chin slightly lifted",

    "turned away from the camera with his head twisted back over one shoulder, "
    "chin near the shoulder line",

    "with his arms folded across his chest, shoulders squared, "
    "head tipped slightly down and eyes level with the lens",

    "resting the side of his face against his own raised hand, elbow propped, "
    "shoulders dropped and relaxed",

    "with one hand curled loosely near his jaw and the other arm hanging out of frame, "
    "head angled three-quarters toward the camera",

    "pressing his back flat to the wall with both hands behind him, "
    "chin lifted and gaze cast slightly downward at the lens",

    "with his head tipped back against the wall and his eyes lowered toward the camera, "
    "one hand loose at the neckline of his top",

    "reaching one hand up to grip the collar of his outer layer and pull it away from his neck, "
    "head turned slightly aside",

    "with both hands slipped into the front of his jacket, "
    "shoulders angled and face square to the camera",
]

ANGLES = [
    "shot from a low angle looking slightly up at him",
    "shot from a high angle looking slightly down at him",
    "shot at eye level, straight on",
    "shot with the camera slightly tilted, a dynamic diagonal frame",
    "shot from the side at a three-quarter angle",
]

# ── 의상 색 규칙 ─────────────────────────────────────────────
# "muted"  = 레퍼런스 룩북 기준. 카키·세이지·크림·오프화이트 뮤트톤 + 포인트 컬러 1점 허용
# "mono"   = 완전 무채색. 블랙·차콜·그레이·화이트만
PALETTE_MODE = "muted"

PALETTES = {
    "muted": (
        "Clothing palette: washed-out tones — faded black, washed ivory, soft white, "
        "stone grey, pale sand, muted navy, with at most one single desaturated accent color. "
        "Fabrics look slightly worn and sun-faded rather than brand new. "
        "Every garment is one flat solid color. "
        "No colour-blocking, no gradients, no contrast panels, no piping, no stripes, no patterns. "
        "No prints, no brand logos, no large graphics, no lettering on any garment."
    ),
    "mono": (
        "Clothing palette: strictly achromatic — black, charcoal, grey, white only. "
        "Absolutely no beige, no cream, no brown, no color of any kind. "
        "No prints, no brand logos, no large graphics."
    ),
}


# ── 프리셋 ───────────────────────────────────────────────────
# key: (한글 라벨, 얼굴/분위기 묘사)
PRESETS = {
    # key: (한글 라벨, 얼굴/분위기 묘사)
    "cat": (
        "고양이상 · 시크",
        "Cat-like face type: rounded eyes with a slight upward outer tilt, small delicate face, "
        "cool and aloof expression, lips softly closed, calm distant gaze.",
    ),
    "dog": (
        "강아지상 · 청량",
        "Puppy-like face type: big round friendly eyes, soft rounded features, "
        "bright open smile with teeth slightly showing, warm approachable energy.",
    ),
    "wolf": (
        "늑대상 · 다크",
        "Wolf-like face type: sharp upward-tilted eyes, defined brow ridge, high cheekbones, "
        "intense direct stare, mouth firmly closed, dangerous charisma.",
    ),
    "fox": (
        "여우상 · 무드",
        "Fox-like face type: long narrow eyes with upward outer corners, slender face, "
        "faint knowing half-smile, seductive relaxed gaze.",
    ),
    "deer": (
        "사슴상 · 몽환",
        "Deer-like face type: large wide-set innocent eyes, long lashes, small soft mouth, "
        "gentle vulnerable expression, slightly parted lips.",
    ),
}



# ── 랜덤 축 1: 헤어 풀 ───────────────────────────────────────
HAIR = [
    "soft black hair with a light wispy fringe",
    "jet black hair, short and neatly cropped, forehead partly showing",
    "natural dark brown hair, fluffy forward styling",
    "medium brown hair, soft curtain bangs parted in the middle",
    "light ash brown hair with loose natural waves",
    "dark ash hair swept back, forehead fully exposed",
    "black hair in a soft two-block cut, sides trimmed short",
    "warm chestnut brown hair, slightly messy bedhead texture",
    "milk tea beige hair, straight and sleek",
    "deep navy-black hair, longer length covering the ears",
    "brown hair with a light perm, soft volume on top",
    "dark hair pushed back with a few loose strands on the forehead",
    "black hair in a soft textured mullet, longer at the nape",
    "bleached platinum blonde hair with dark roots showing",
    "dark hair with thin face-framing strands falling past the jaw",
    "ash grey hair, choppy layered cut with visible texture",
    "black shaggy wolf cut, long wispy fringe falling into the eyes, tapered long at the nape",
    "a blunt bowl cut with a straight heavy fringe sitting just above the eyebrows",
    "messy grown-out layers with piecey separated strands framing the cheekbones",
    "dark brown mushroom cut, rounded and blunt, fringe covering the forehead",
]



# ── 랜덤 축 2: 의상 ──────────────────────────────────────────
# 채택된 방향: 조용한 무채색 아우터를 열어 입고 이너는 무지 한 장. 장식·프린트·컬러블록 없음.
# (문구, 가중치) — 4 = 채택 3종, 1 = 같은 결의 변주.
# 걷어낸 것: 컬러블록 나일론, 바시티, 트랙탑 파이핑, 아노락, 메쉬, 스터드 벨트,
#            빨간 안감 바이커 — 전부 "과하다"로 반려됨.
# 여자 생성 시 제외할 헤어 — 밥·보울컷으로 나오는 항목
HAIR_EXCLUDE_F = ("bowl cut", "mushroom cut", "short and neatly cropped", "two-block")


def hair_pool(gender):
    if gender == "f":
        return [h for h in HAIR if not any(k in h for k in HAIR_EXCLUDE_F)]
    return HAIR


OUTFITS = [
    ("a black coach jacket snapped only partway, worn over a plain off-white tee", 4),

    ("a cropped black denim jacket worn open but sitting squarely on both shoulders, "
     "over a fitted white ribbed tank", 4),

    ("a slouchy grey sweatshirt with a wide stretched neckline slipping off one shoulder", 4),

    ("a washed ivory oversized shirt worn open with the sleeves rolled once, "
     "a plain black long-sleeve tee underneath", 2),

    ("an unbuttoned washed denim overshirt worn loose over a plain white tee", 2),

    ("a plain black shirt jacket buttoned partway, worn over a plain white tee", 2),

    ("a faded black long-sleeve tee with the sleeves pushed up to the forearm, minimal and clean", 1),

    ("a boxy oversized tee in one solid washed tone, sleeves falling past the elbow", 1),

    ("a soft black leather bomber jacket worn open, collar loose, over a plain white tee", 1),

    ("an oversized off-white sweatshirt with a plain round neck, soft and worn-in", 1),
]





# 액세서리 — 채택본들이 거의 민짜. 안경은 과하다는 피드백으로 제거.
ACCESSORIES = [
    "", "", "", "", "", "", "", "", "", "",   # 10/13 확률로 없음
    "a single small silver earring",
    "a few small silver hoops in one ear",
    "one or two thin silver rings",
]


# ── 랜덤 축 3: 미세 변형 ─────────────────────────────────────
# 8개 카테고리에서 매번 정확히 하나씩 뽑는다. 순서 고정.
# 골격 4개(JAW/CHIN/MIDFACE/CHEEKBONES) + 이목구비 3개(EYES/NOSE/LIPS) + 식별 특징 1개.
SLOT_ORDER = ["JAW", "CHIN", "MIDFACE", "CHEEKBONES", "EYES", "NOSE", "LIPS",
              "DISTINCTIVE_FEATURE"]

VARIATIONS = {
    "eye_spacing":  ["slightly wide-set eyes", "slightly close-set eyes", "evenly spaced eyes"],
    "eyelid":       ["clear double eyelids", "thin inner double eyelids",
                     "soft mono-lid with a subtle crease"],
    "eye_size":     ["large round eyes", "long almond eyes", "gently drooping puppy eyes"],
    "brow":         ["straight soft brows", "slightly arched brows", "thick natural brows",
                     "light thin brows"],
    "nose":         ["a slim straight nose", "a small rounded nose tip", "a high refined nose bridge"],
    "lips":         ["full soft lips", "thin neat lips", "a slightly pouty lower lip"],
    "vibe":         ["a calm quiet air", "a bright playful air", "a soft sleepy air",
                     "a poised confident air"],
}
N_VARIATIONS = 4   # 위에서 매번 몇 개를 뽑을지

# ── 식별 표식: 점 / 주근깨 / 보조개 ──────────────────────────
# 얼굴을 "다른 사람"으로 읽히게 하는 가장 강한 축이라 매번 세 축 모두 뽑는다.
# 빈 문자열이 섞여 있어 아무 표식도 없는 얼굴도 나온다.
MARKS = {
    "mole": [
        "", "", "",
        "a small mole just beneath one eye",
        "a tiny mole at the outer corner of one eye",
        "a small beauty mark near the corner of the mouth",
        "a faint mole just below the lower lip",
        "a tiny mole on one cheek",
        "a small mole beside the nose",
        "a tiny mole on the jawline",
        "a small mole on the neck below the ear",
        "two tiny moles close together on one cheek",
    ],
    "freckles": [
        "", "", "", "",
        "a light dusting of freckles across the nose and upper cheeks",
        "a few faint freckles scattered over the nose bridge",
        "sparse pale freckles high on both cheekbones",
        "very subtle freckles barely visible under the eyes",
        "soft sun-freckles across the nose, natural and uneven",
    ],
    "dimple": [
        "", "", "", "",
        "a soft dimple in one cheek when the mouth moves",
        "matching dimples in both cheeks",
        "a shallow dimple low near the corner of the mouth",
        "a faint dimple in the chin",
    ],
}

MARKS_RULE = (
    "Any moles, freckles or dimples stay small, faint and natural — "
    "never exaggerated, never symmetrical patterns, never drawn-on looking."
)


# 얼굴상 뒤에 붙는 설명
FACETYPE_NOTE = (
    "The selected face type defines the overall impression and eye expression, "
    "while the Individual details create subtle personal variation without changing "
    "the fundamental face type."
)

# Individual details 앞뒤 가드
DETAILS_RULE = (
    "Individual details must contain exactly one feature from each of the following "
    "eight categories. The eight features must complement one another. "
    "Do not introduce contradictory or extreme facial characteristics. "
    "The individual remains within the youthful, delicate, narrow facial proportions "
    "established above."
)
DETAILS_GUARD = (
    "Distinctive features must remain subtle and natural. "
    "Never exaggerate asymmetry, moles, freckles, or facial irregularities."
)

# 같은 얼굴로 수렴하는 걸 막는 지시
DISTINCT = (
    "This is a distinct individual with their own unique combination of facial proportions "
    "and subtle characteristics. "
    "Preserve the selected Individual details exactly, especially the jaw shape, "
    "chin proportions, midface proportions, cheekbone structure, eye shape, nose structure, "
    "and lip shape. "
    "Avoid the generic standardized K-pop idol face. The person should look like a believable "
    "unique individual while remaining extremely attractive, youthful, and photorealistic."
)

# 섹션별 가드
HAIR_RULE = (
    "Hair must be fully visible from the roots to the ends. Do not obscure the entire face. "
    "Natural individual hair strands, realistic volume, and believable hair texture."
)
OUTFIT_RULE = (
    "Clothing must remain properly worn and fully cover the shoulders, upper arms, "
    "and chest as instructed above."
)
ACCESSORY_RULE = (
    "Accessories must remain subtle and must never obscure the eyes, nose, mouth, jawline, "
    "or overall facial structure."
)

# ── 레퍼런스 이미지 ──────────────────────────────────────────
# face  : 동물상별 매칭 (파일명 접두사 = 한글 동물상). 얼굴 인상 + 헤어 담당
# pose  : 성별별 랜덤. 포즈 · 시선 · 상체 각도 담당
# outfit: 성별별 랜덤. 의상만 담당 (무신사 룩북 컷이라 워터마크/전신/배경은 무시)
DESKTOP = "/Users/jeonjei/Desktop"
REF_DIRS = {
    "face":   {"m": f"{DESKTOP}/face_boy",   "f": f"{DESKTOP}/face_girl"},
    "pose":   {"m": f"{DESKTOP}/pose_boy",   "f": f"{DESKTOP}/pose_girl"},
    "outfit": {"m": f"{DESKTOP}/outfit_boy", "f": f"{DESKTOP}/outfit_girl"},
}
REF_PREFIX = {
    "cat": "고양이상", "dog": "강아지상", "wolf": "늑대상",
    "fox": "여우상",   "deer": "사슴상",
}
REF_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# 첨부 순서대로 역할을 명시한다. 순서가 어긋나면 모델이 뒤섞어 해석한다.
# 레퍼런스와 "닮았지만 다른 사람"을 만드는 장치.
# 추상적인 "다른 사람으로 만들라"는 잘 안 먹혀서, 레퍼런스 대비 구체적 편차를 매번 2~3개 지정한다.
# 같은 레퍼런스에서 매번 다른 얼굴이 나오게 하는 역할도 겸한다.
DEVIATIONS = [
    "make the face noticeably longer and narrower than in the reference",
    "make the face shorter and rounder than in the reference",
    "set the eyes a little further apart than in the reference",
    "set the eyes a little closer together than in the reference",
    "make the eyes larger and rounder than in the reference",
    "make the eyes longer and narrower than in the reference",
    "make the nose smaller and less prominent than in the reference",
    "give a higher, straighter nose bridge than the reference",
    "give noticeably fuller lips than the reference",
    "give thinner, neater lips than the reference",
    "make the jaw softer and less defined than in the reference",
    "make the chin shorter and rounder than in the reference",
    "raise the brow line slightly compared to the reference",
    "give thicker, straighter brows than the reference",
    "give a shorter midface than the reference, features sitting closer together",
    "give fuller cheeks than the reference",
]
N_DEVIATIONS = 3

REF_ROLE = {
    "face": (
        "the FACE reference. Follow it for the FACE TYPE and overall impression — the general "
        "shape and feel of the face, the character of the eyes, the youthful atmosphere — "
        "and for the hair: its length, colour, cut, texture and styling. "
        "This is NOT the same person and must never be recognizable as them. "
        "Apply the deviations listed above exactly: they are the differences that make this a "
        "separate individual who merely shares the same face type. "
        "Do not copy the reference's distinctive marks, moles or exact features. "
        "Ignore this photo's background, clothing, pose, camera angle, lighting and colour "
        "grading, and any text, watermark or logo on it."
    ),
    "pose": (
        "the POSE reference. Copy ONLY the body pose from it — the angle of the torso and "
        "shoulders, the position of the arms and hands, the tilt of the head and the direction "
        "of the gaze. Ignore this photo's person, face, hair, clothing, background, lighting "
        "and colour grading completely."
    ),
    "outfit": (
        "the OUTFIT reference. Copy ONLY the clothing from it — the garments, their fit, "
        "layering, neckline, silhouette, fabric and colour. Ignore this photo's person, face, "
        "hair, pose, background, lighting and colour grading completely, and ignore any text, "
        "watermark, logo or brand mark printed on or beside it. "
        "Reproduce only the parts of the outfit that fall inside the crop of the final image."
    ),
}


def _nfc(x):
    return unicodedata.normalize("NFC", x)


def ref_pool(kind, gender, key=None):
    """kind = face | pose | outfit. face 는 key(프리셋)로 동물상 매칭."""
    d = REF_DIRS[kind][gender]
    if not os.path.isdir(d):
        return []
    prefix = _nfc(REF_PREFIX[key]) if (kind == "face" and key) else None
    return sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if f.lower().endswith(REF_EXTS) and (prefix is None or _nfc(f).startswith(prefix))
    )


def ref_instruction(kinds):
    """첨부된 레퍼런스 종류를 순서대로 설명하는 문장을 만든다."""
    if not kinds:
        return ""
    ordinals = ["The first", "The second", "The third"]
    parts = [f"{ordinals[i]} attached photo is {REF_ROLE[k]}" for i, k in enumerate(kinds)]
    head = (f"{len(kinds)} reference photos are attached, in this order. " if len(kinds) > 1
            else "A reference photo is attached. ")
    return " " + head + " ".join(parts)


_FEM_MAP = {"he": "she", "his": "her", "him": "her", "himself": "herself",
            "He": "She", "His": "Her", "Him": "Her"}


def _fem(text):
    """풀 문구에 쓰인 남성 대명사를 여성형으로 바꾼다."""
    return re.sub(r"\b(he|his|him|himself|He|His|Him)\b",
                  lambda m: _FEM_MAP[m.group()], text)


def build_prompt(key, rng, refs=None, mode=None, add=None, override=None, gender=None):
    """refs — 첨부할 레퍼런스 종류 리스트. 예: ["face", "pose", "outfit"]
              face 가 있으면 Hair, pose 가 있으면 Pose, outfit 이 있으면 Outfit 텍스트를 생략한다.
       add      — 맨 뒤에 덧붙일 문장
       override — 프리셋 무시, 이 문장만 사용 (BASE 유지)
    """
    mode = mode or SHOT_MODE
    gender = gender or GENDER
    refs = refs or []
    base = base_block(gender, face_ref="face" in refs)
    ref_part = ref_instruction(refs)
    if override:
        return f"{base} {override}{ref_part}"

    label, face = PRESETS[key]
    subj = "She" if gender == "f" else "He"

    picked = rng.sample(list(VARIATIONS), min(N_VARIATIONS, len(VARIATIONS)))
    micro = [rng.choice(VARIATIONS[k]) for k in picked]
    marks = [m for m in (rng.choice(MARKS[k]) for k in ("mole", "freckles", "dimple")) if m]
    dev_part = ""
    if "face" in refs:
        picks = rng.sample(DEVIATIONS, N_DEVIATIONS)
        dev_part = ("Compared to the attached face reference, this person differs as follows: "
                    + "; ".join(picks) + ". These differences are mandatory. ")
    details = ", ".join(micro + marks)
    marks_rule = f" {MARKS_RULE}" if marks else ""

    # 레퍼런스가 담당하는 축은 텍스트로 또 지정하지 않는다 — 서로 상쇄된다.
    hair_part = "" if "face" in refs else f"Hair: {rng.choice(hair_pool(gender))}. "

    if "outfit" in refs:
        outfit_part = ""
    else:
        outfit = rng.choices([o for o, _ in OUTFITS], weights=[w for _, w in OUTFITS])[0]
        acc = rng.choice(ACCESSORIES)
        acc_part = f" {subj} is wearing {acc}." if acc else ""
        if gender == "f":
            outfit, acc_part = _fem(outfit), _fem(acc_part)
        outfit_part = f"Outfit: {outfit}.{acc_part} {PALETTES[PALETTE_MODE]} "

    pose_part = ""
    if mode == "editorial" and "pose" not in refs:
        pose_part = f"Pose: {subj.lower()} is {rng.choice(POSES)}, {rng.choice(ANGLES)}. "
        if gender == "f":
            pose_part = _fem(pose_part)

    framing = _fem(FRAMING[mode]) if gender == "f" else FRAMING[mode]
    add_part = f" {add}" if add else ""
    return (
        f"{base} {face} "
        f"Individual details: {details}.{marks_rule} "
        f"{dev_part}"
        f"{hair_part}"
        f"{outfit_part}"
        f"{pose_part}"
        f"{framing}{ref_part}{add_part}"
    )


def token():
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"]
    ).decode().strip()


def _inline(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    ext = os.path.splitext(path)[1].lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp"}.get(ext, "image/png")
    return {"inlineData": {"mimeType": mime, "data": b64}}


def generate(prompt, out_path, tok, location, ref_paths=None, aspect="4:3"):
    """ref_paths — build_prompt 에 넘긴 refs 와 같은 순서여야 한다."""
    parts = [_inline(r) for r in (ref_paths or [])]
    parts.append({"text": prompt})

    body = json.dumps({
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect},
        },
    }).encode()
    url = (f"https://{location}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
           f"/locations/{location}/publishers/google/models/{MODEL}:generateContent")
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"

    for p in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if "inlineData" in p:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(p["inlineData"]["data"]))
            return None
    return "NO IMAGE: " + json.dumps(data)[:200]


REF_KINDS = ["face", "pose", "outfit"]


def main():
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return

    args = [a for a in argv if not a.startswith("-")]

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    n = int(opt("--n", 1))
    seed = opt("--seed")
    mode = opt("--mode", SHOT_MODE)
    gender = opt("--gender", GENDER)
    add = opt("--add")
    override = opt("--prompt")
    want = opt("--refs", "face,pose,outfit")
    if "--no-ref" in argv:
        want = ""
    interactive = "-i" in argv or "--ask" in argv
    for name in ("--n", "--seed", "--mode", "--gender", "--add", "--prompt", "--refs"):
        if name in argv:
            v = argv[argv.index(name) + 1]
            if v in args:
                args.remove(v)

    kinds = [k.strip() for k in want.split(",") if k.strip()]
    bad_k = [k for k in kinds if k not in REF_KINDS]
    if bad_k:
        print(f"모르는 레퍼런스 종류: {bad_k}\n사용 가능: {REF_KINDS}")
        sys.exit(1)

    genders = ["m", "f"] if gender == "both" else [gender]
    if any(g not in _SUBJECT for g in genders):
        print(f"모르는 성별: {gender}\n사용 가능: m, f, both")
        sys.exit(1)

    if interactive:
        print("직접 넣을 프롬프트를 입력하세요. 그냥 엔터 = 프리셋 그대로.")
        print("  1) 덧붙이기   2) 대체")
        choice = input("방식 [1/2, 기본 1]: ").strip() or "1"
        text = input("프롬프트: ").strip()
        if text:
            override, add = (text, None) if choice == "2" else (None, text)

    if add and override:
        print("--add 와 --prompt 는 같이 못 씁니다.")
        sys.exit(1)
    if mode not in FRAMING:
        print(f"모르는 모드: {mode}\n사용 가능: {list(FRAMING)}")
        sys.exit(1)

    keys = args or list(PRESETS)
    bad = [k for k in keys if k not in PRESETS]
    if bad:
        print(f"모르는 프리셋: {bad}\n사용 가능: {list(PRESETS)}")
        sys.exit(1)

    rng = random.Random(int(seed) if seed else None)

    # 레퍼런스 풀 미리 수집
    pools = {}
    for g in genders:
        for k in kinds:
            if k == "face":
                for key in keys:
                    pools[(g, k, key)] = ref_pool(k, g, key)
            else:
                pools[(g, k, None)] = ref_pool(k, g)

    print(f"모드: {mode} ({ASPECT[mode]}) · 성별: "
          + ", ".join("남자" if g == "m" else "여자" for g in genders))
    if kinds:
        for g in genders:
            bits = []
            for k in kinds:
                if k == "face":
                    tot = sum(len(pools[(g, k, key)]) for key in keys)
                    miss = [PRESETS[key][0].split(" · ")[0]
                            for key in keys if not pools[(g, k, key)]]
                    bits.append(f"face {tot}장" + (f"(없음: {','.join(miss)})" if miss else ""))
                else:
                    bits.append(f"{k} {len(pools[(g, k, None)])}장")
            print(f"  {'남자' if g == 'm' else '여자'} 레퍼런스 — " + " / ".join(bits))
    else:
        print("  레퍼런스 사용 안 함")
    if add:
        print(f"덧붙인 프롬프트: {add}")
    if override:
        print(f"프롬프트 대체: {override}")

    os.makedirs(OUT_DIR, exist_ok=True)
    tok = token()
    jobs = [(g, k, i) for g in genders for k in keys for i in range(1, n + 1)]

    for idx, (g, key, i) in enumerate(jobs):
        label = PRESETS[key][0] + (" · 여자" if g == "f" else " · 남자")
        out = os.path.join(OUT_DIR, f"{g}_{key}_{i:02d}.png")

        used, paths = [], []
        for k in kinds:
            pool = pools[(g, k, key)] if k == "face" else pools[(g, k, None)]
            if pool:
                used.append(k)
                paths.append(rng.choice(pool))
        tag = (" +" + ",".join(os.path.basename(x) for x in paths)) if paths else ""
        print(f"[{idx+1}/{len(jobs)}] {label} → {os.path.basename(out)}{tag} ... ",
              end="", flush=True)

        prompt = build_prompt(key, rng, refs=used, mode=mode,
                              add=add, override=override, gender=g)
        err = None
        for attempt in range(RETRIES):
            loc = LOCATIONS[(idx + attempt) % len(LOCATIONS)]
            err = generate(prompt, out, tok, loc, ref_paths=paths, aspect=ASPECT[mode])
            if err is None:
                print(f"OK ({loc})")
                break
            if attempt < RETRIES - 1:
                print(f"재시도({loc} 실패) ", end="", flush=True)
                time.sleep(INTERVAL)
        else:
            print(f"실패 — {err}")
        if idx < len(jobs) - 1:
            time.sleep(INTERVAL)

    print(f"\n완료 → {OUT_DIR}")


if __name__ == "__main__":
    main()
