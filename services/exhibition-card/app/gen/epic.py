#!/usr/bin/env python3
"""AI 아이돌 이미지 생성기 — epic (종족 설정 기반)

normal.py 를 import 해서 얼굴 품질·미세변형·표식·편차·레퍼런스·생성 로직을 재사용하고,
프롬프트만 다르게 조립한다. normal 의 일상복 제약(모자·민소매 금지, 단색, 노출 금지)은
코스프레와 충돌하므로 상속하지 않는다.

크롭이 가슴 위라 꼬리·지느러미·날개는 보이지 않는다. 종족 특징은 머리·목·어깨에 몰아넣는다.

종족: ninetail(구미호) cat(묘인) devil(악마) angel(천사) fairy(요정) mermaid(인어)

기본:
    python3 epic.py                            # 전 종족 1장씩
    python3 epic.py mermaid devil              # 특정 종족만
    python3 epic.py --n 3                      # 종족당 3장
    python3 epic.py --gender both              # 남녀 동시 (m | f | both)
    python3 epic.py --face wolf                # 얼굴상 고정 (기본: 종족별 기본 얼굴상)
    python3 epic.py --seed 42                  # 같은 결과 재현
    python3 epic.py --add "..."                # 프롬프트 덧붙이기

레퍼런스:
    기본값 pose,cosplay — 코스프레 레퍼런스가 의상·메이크업·액세서리·분위기·얼굴을 담당한다.
    cosplay_boy 폴더가 없으므로 남자는 --refs face,pose 로 돌리고 의상은 텍스트 폴백을 쓴다.

    python3 epic.py --refs pose,cosplay        # 기본
    python3 epic.py --refs face,pose           # 남자용
    python3 epic.py --no-ref                   # 전부 끄기

결과 보기:
    python3 sheet.py out
"""
import os, random, sys, time

import normal as N

OUT_DIR = N.OUT_DIR
ASPECT = "3:4"          # epic 은 화보컷 고정
REF_KINDS = ["face", "pose", "cosplay"]
# normal 의 outfit 레퍼런스(무신사 룩북)는 종족 컨셉과 충돌하므로 쓰지 않고,
# 대신 실사 코스프레 사진에서 의상·메이크업·액세서리만 가져온다.
CLEAN_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refs_clean")
# prep_refs.py 로 하단 워터마크를 잘라낸 사본. 없으면 원본으로 폴백.
COSPLAY_DIRS = {"f": os.path.join(CLEAN_ROOT, "cosplay_girl")}
if not os.path.isdir(COSPLAY_DIRS["f"]):
    COSPLAY_DIRS = {"f": "/Users/jeonjei/Desktop/cosplay_girl"}

# normal 쪽 face/pose 레퍼런스도 사본이 있으면 그쪽을 쓴다
for _kind in ("face", "pose"):
    for _g, _suffix in (("m", "boy"), ("f", "girl")):
        _c = os.path.join(CLEAN_ROOT, f"{_kind}_{_suffix}")
        if os.path.isdir(_c):
            N.REF_DIRS[_kind][_g] = _c
COSPLAY_ROLE = (
    "the STYLING reference. Copy ONLY three things from it: "
    "(1) the outfit — garments, fabric, neckline, layering, colour; "
    "(2) the makeup — eye makeup, colour of the contact lenses, glitter, face gems, "
    "any painted or applied markings on the skin; "
    "(3) the accessories and headpiece — horns, ears, shells, jewellery, chains, pearls, "
    "hair ornaments, and how they sit on the head; the hair itself — its colour, length and styling, including wigs; "
    "(4) the FACE — follow this photo for the facial style and beauty standard: "
    "the face shape and proportions, the eye shape and how the eyes are set, "
    "the nose and mouth, the striking doll-like cosplayer look. "
    "This face is the target, not a plain everyday face. "
    "Apply the deviations listed above so it is a different person, "
    "but keep that same level of striking, sharply-featured beauty. "
    "Reproduce those at FULL strength and at the same level of craft: real physical props and "
    "real makeup on skin. Do not tone it down, do not simplify it, do not swap it for "
    "ordinary clothing — match or exceed how elaborate the reference styling is. "
    "Ignore this photo's person, face, facial structure, body, pose, expression, background "
    "and lighting completely. Ignore any watermark, username, ID text or logo on it, "
    "and any phone, mirror or dressing-room clutter visible in it. "
    "Reproduce only the parts that fall inside the crop of the final image."
)


def cosplay_pool(gender, species_key):
    d = COSPLAY_DIRS.get(gender)
    if not d or not os.path.isdir(d):
        return []
    pre = N._nfc(species_key)
    return sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if f.lower().endswith(N.REF_EXTS) and N._nfc(f).startswith(pre)
    )

# ── epic 전용 BASE ───────────────────────────────────────────
# normal 의 BASE 는 일상복 규칙(모자·민소매·조끼 금지, 팔가슴 가리기, 단색, 프린트 금지)을
# 담고 있어 코스프레 스타일링과 정면으로 충돌한다. epic 은 그 제약을 걷어낸다.
EPIC_SUBJECT = {
    "m": ("Photorealistic photo of an extremely handsome Korean male idol, "
          "visibly around 20 years old, youthful and boyish, never appearing older than 22.", "He", "his"),
    "f": ("Photorealistic photo of an extremely beautiful Korean female idol, "
          "visibly around 20 years old, fresh and youthful, never appearing older than 22.", "She", "her"),
}

EPIC_SHARED = (
    "Large clear eyes and a slim clean jawline — never wide, square or heavy. "
    "High detail. Must NOT resemble any real celebrity. "
    "Absolutely no text, no letters, no numbers, no watermark, no logo anywhere in the image — "
    "no lettering on any garment."
)

# 스타일링을 최대치로 끌어올린다. 이게 epic 을 normal 과 가르는 축이다.
COSTUME_RULE = (
    "This is a full fantasy character look, not everyday clothing. "
    "The costume, makeup and headpiece are ELABORATE, THEATRICAL and heavily detailed — "
    "ornate fabric, layered construction, sculpted headpiece, statement jewellery, "
    "BOLD heavy stage makeup — strongly defined eyeliner with a long drawn-out tail, "
    "deep smoked and blended eyeshadow, saturated blush washed high across the cheeks and "
    "under the eyes, sharply drawn lips, false lashes, coloured contact lenses, "
    "and applied gems, glitter or painted markings on the skin where the look calls for it. "
    "The makeup is theatrical and clearly visible, never bare-faced, never a natural no-makeup look. "
    "Never reduce it to a plain t-shirt, a cardigan, a hoodie or ordinary streetwear. "
    "Headpieces, horns, ears, crowns and hair ornaments are required parts of the look. "
    "Bare shoulders, sheer panels and decorative straps are allowed if the look calls for it. "
    "Every visible element should read as a costume built for a photoshoot."
)


def epic_base(gender):
    subject, they, their = EPIC_SUBJECT[gender]
    return f"{subject} {EPIC_SHARED}"


# ── 종족 ─────────────────────────────────────────────────────
# key: (한글 라벨, 기본 얼굴상, 외형, 의상, 조명·분위기)
SPECIES = {
    # key: (한글 라벨, 기본 얼굴상, 외형(해부), 의상 폴백, 조명·분위기)
    "ninetail": (
        "구미호", "fox",
        "A pair of soft fox ears rise from the hair, fur matching the hair colour exactly, "
        "lined with pale cream inside, set naturally into the hairline. "
        "The irises are molten gold with a faint vertical slit. "
        "A single faint fox-fire mark curls at the outer corner of one eye.",
        "a dark silk hanbok-inspired top with a deep crossed collar and a long tie at the chest",
        "warm amber rim light from behind with cool shadow in front, shot in a dark studio",
    ),
    "cat": (
        "묘인", "cat",
        "A pair of small cat ears rise from the hair, short dense fur matching the hair colour, "
        "one ear flicked slightly off-axis, set naturally into the hairline. "
        "The irises are clear green-gold with a narrow vertical slit pupil. "
        "Very fine pale whisker-dots sit high on the cheeks, barely visible.",
        "a fitted black knit top with a wide open neckline",
        "soft directional light with a gentle falloff, shot against a plain mid-grey studio wall",
    ),
    "devil": (
        "악마", "fox",
        "Two curved dark horns sweep back and out from above the temples, matte and ridged, "
        "growing naturally out of the skull under the hairline. "
        "The irises are deep crimson ringed darker at the edge. "
        "A faint darker flush sits under the outer eye corners.",
        "a black textured top with a deep neckline and fine silver chains at the throat",
        "hard low-key light from one side, deep red-black falloff behind",
    ),
    "angel": (
        "천사", "deer",
        "A thin ring of pale light hovers just above the crown of the head, faint and weightless. "
        "Fine luminous markings trace the outer brow and the bridge of the nose, "
        "glowing softly from under the skin. "
        "The irises are near-white with a pale gold ring.",
        "layered white and pale gold cloth draped across the shoulders with a high back collar",
        "diffuse light from everywhere at once, no hard shadow, shot in a bright white studio",
    ),
    "fairy": (
        "요정", "dog",
        "The outer ears are long and delicately pointed, tapering back past the hairline, "
        "skin-toned and anatomically continuous with the head. "
        "The irises are pale spring green flecked with gold. "
        "A faint dusting of iridescent shimmer sits along the cheekbones and brow.",
        "a sheer layered wrap in soft petal tones over the shoulders",
        "warm dappled light as if filtered through leaves, soft green-gold bokeh behind",
    ),
    "mermaid": (
        "인어", "deer",
        "In place of outer ears, translucent fin-like membranes fan back from the sides of the "
        "head, faintly iridescent and veined with pale blue. "
        "A scatter of tiny opalescent scales runs along the cheekbones, temples and down the "
        "side of the neck, catching light like wet glass. "
        "The irises are pale aquamarine with a wide dark pupil.",
        "a draped translucent wrap in sea-glass tones with small freshwater pearls at the collarbone",
        "cool light from above with soft caustic ripples across the skin, "
        "the background deep blue-green and fading",
    ),
}

# 종족 외형이 프롬프트 뒤쪽에서 다시 눌리지 않도록 못을 박는다
SPECIES_RULE = (
    "IMPORTANT — this is a REAL PHOTOGRAPH of a real human model on a real photo set. "
    "The species traits are achieved with practical special-effects makeup and prosthetics "
    "applied to that model: silicone appliances blended into the skin, hand-punched real hair, "
    "airbrushed colour, custom contact lenses. Photograph the result. "
    "The prosthetics are seamless and convincing — no visible edges, no glue, no headbands, "
    "no clip-ons, no costume-shop props. "
    "Everything obeys real camera physics: real skin with visible pores and fine peach fuzz, "
    "subsurface scattering, natural specular highlights, shallow depth of field with real lens "
    "falloff, faint sensor grain. "
    "NOT an illustration, NOT digital painting, NOT anime, NOT concept art, NOT a 3D render, "
    "NOT smooth airbrushed CGI skin. "
    "The species traits must still be clearly visible and correctly rendered — "
    "they are the defining feature of the image."
)

# 미남·미녀 베이스라인이 피부를 계속 매끈하게 밀어버려서, 프롬프트 맨 뒤에 따로 못을 박는다.
SKIN_RULE = (
    "SKIN — this is critical. The skin is REAL photographed skin, not retouched and not CGI. "
    "Visible pores across the nose, cheeks and forehead. Fine peach fuzz catching the light "
    "along the jaw and upper lip. Slight natural unevenness in tone, faint redness around the "
    "nostrils and inner eye corners, a few small natural blemishes or texture marks. "
    "Real specular highlights that sit on top of the skin, subsurface scattering in the ears "
    "and around the nose. Makeup sits ON the skin as a physical layer — you can see where "
    "powder catches texture and where cream product breaks over pores. "
    "Absolutely NOT a smooth airbrushed plastic surface, NOT a beauty-filter finish, "
    "NOT wax, NOT porcelain, NOT a 3D render."
)

# 채택 기준컷(epic_f_mermaid_01)의 특성을 epic 전체의 하우스 스타일로 고정한다.
# 분위기·색은 코스프레 레퍼런스를 따르되, 그 위에 이 트리트먼트를 얹는다.
HOUSE_LOOK = (
    "Overall treatment: shot on location in the style of a Y2K digital compact camera snapshot. "
    "Light falls softly on the face and slightly overexposes it — highlights on the forehead, "
    "nose and cheekbones lift toward white, and the whole image sits a little hot. "
    "Skin reads bright and washed with a warm pink flush across the cheeks, nose and eyelids. "
    "Shadows are shallow, weak and warm — almost none on the face. "
    
    "Fine loose strands of hair blow across the face and catch the sun, glowing bright white "
    "where the light passes through them. "
    "Slight softness and low micro-contrast from a small cheap sensor, gentle veiling glare "
    "washing over part of the frame, faint noise. "
    "Vertical phone-held framing, casual and immediate rather than studio-lit."
)

# 표정 — 프리셋 얼굴상에 박힌 표정과 포즈 레퍼런스가 겹쳐 매번 같은 얼굴이 나오므로
# 별도 축으로 뽑아 프롬프트 뒤쪽에 넣어 덮어쓴다.
EXPRESSIONS = [
    "a wide open smile with the teeth showing and the eyes crinkled shut",
    "a bright grin with the teeth showing, chin lifted, caught mid-laugh",
    "a soft closed-mouth smile with the eyes curved into crescents",
    "a small private smile at one corner of the mouth, eyes steady on the lens",
    "a cool blank stare, lips relaxed and slightly parted, no expression at all",
    "a cold hard glare, chin dropped, looking up through the lashes",
    "eyebrows raised and eyes wide, caught slightly startled",
    "eyes lowered and turned away from the lens, lashes casting shadow, quiet and withdrawn",
    "head tipped back, eyes half-closed, languid and unbothered",
    "a smirk with one eyebrow raised, clearly amused at something off camera",
    "lips pressed together and eyes narrowed, sizing the viewer up",
    "mouth open in a soft gasp, eyes round, genuinely surprised",
    "a pout with the lower lip pushed out, brows drawn slightly together",
    "one eye squeezed shut in a wink, mouth pulled into a crooked grin",
    "chin resting down, gaze flicked sideways to the lens, sly and knowing",
    "a serene, almost sad look, mouth soft and unsmiling, eyes distant",
    "teeth caught on the lower lip, eyes bright, holding back a laugh",
    "brows lifted in the middle, eyes soft and pleading, mouth small",
]

# 종족별 배경 환경. 인물은 여전히 클로즈업이라 환경은 아웃포커스로만 읽힌다.
ENVIRONMENTS = {
    "mermaid": "underwater, fully submerged in deep blue-green water. "
               "Shafts of light come down from the surface far above and caustic ripples move "
               "across the skin. Tiny bubbles drift past. Hair floats and lifts, weightless. "
               "The water gets darker and hazier with distance behind her.",
    "devil":   "inside fire — standing in the middle of open flame. "
               "Orange and red firelight comes from below and behind, licking up around the edges "
               "of the frame, with drifting embers and dark smoke. "
               "The background is a deep glowing red-black haze of heat.",
    "fairy":   "deep in a forest, surrounded by trees and undergrowth. "
               "Sunlight breaks through the canopy in scattered shafts and dapples the face. "
               "Green leaves and ferns crowd the frame, thrown far out of focus into soft bokeh.",
    "cat":     "inside an old warehouse — bare concrete, steel beams and stacked wooden crates. "
               "Hard daylight cuts in through a high dusty window and lights the face, "
               "with the rest of the space falling into dim shadow. Dust hangs in the light.",
    "angel":   "high up among clouds, standing in open sky. "
               "Soft white cloud fills the frame all around, glowing and backlit, with pale blue "
               "sky above. The light is bright, diffuse and comes from everywhere at once.",
    "ninetail": "deep in mountains — misty forested ridges receding behind her. "
                "Cool morning light through drifting mountain fog, pine and bare rock softly out "
                "of focus in the distance.",
}

ENV_RULE = (
    "The environment is real and physically present around the subject — the same light that "
    "lights the scene lights the face, and the subject is clearly IN the place, not composited "
    "in front of it. It stays well out of focus behind her and never competes with the face."
)

# 손에 든 소품 — 채택본(소라를 든 인어)처럼 생동감을 만든다. 대부분은 없음.
PROPS = {
    "ninetail": ["", "", "", "a folded paper fan held near the face",
                 "a small brass bell on a cord"],
    "cat": ["", "", "", "a small bell charm held between two fingers", "a sprig of dried flowers"],
    "devil": ["", "", "", "a thin silver chain looped over the fingers",
              "a small dark stone held up to the light"],
    "angel": ["", "", "", "a single white feather held between the fingers",
              "a sprig of baby's breath"],
    "fairy": ["", "", "", "a small wildflower held near the cheek",
              "a sprig of green leaves"],
    "mermaid": ["", "", "", "a large conch shell held up in both hands",
                "a scallop shell resting in the palm"],
}

EXPRESSION_RULE = (
    "The expression is the emotional centre of the image and overrides any expression implied "
    "by the face type or the pose reference. It must read clearly and reach the eyes — "
    "the whole face moves, not just the mouth."
)

# AI 티의 정체는 "완벽함"이다. 실제 촬영에서 반드시 생기는 결함을 명시적으로 요구한다.
PHOTO_RULE = (
    "THIS IS A REAL PHOTOGRAPH, and it must fail in the ways real photographs fail. "
    "Shot on a full-frame camera with a fast prime lens, wide open. "
    "Focus is on the near eye and falls off measurably — the far eye and the ear are already "
    "slightly soft, the shoulders and costume edges softer still. "
    "Visible fine noise across the frame, especially in the flat background. "
    "Faint chromatic aberration on high-contrast edges. Slight vignetting in the corners. "
    
    "The face is NOT symmetrical — the two sides differ in shape, the eyes differ slightly in "
    "size and height, one eyebrow sits higher. "
    "Stray flyaway hairs cross the face and catch the light. "
    "Nothing is perfectly placed: the headpiece sits a little crooked, a chain has fallen out "
    "of line, fabric is creased and slightly rumpled where it has been worn. "
    "The softness comes from a real cheap lens and real sunlight, not from smoothing: "
    "skin texture stays visible even in the bright areas. "
    "NO airbrushed plastic sheen, NO waxy skin, NO AI-art look, "
    "NO digital-illustration finish, NO 3D render, NO beauty filter."
)

FRAMING = (
    "This is a fashion magazine editorial photo — a styled photoshoot, not a casual snapshot. "
    "Framing: vertical composition, 50mm lens look. Cropped close, at the upper chest. "
    "The head occupies roughly 35 to 40 percent of the frame height and the subject "
    "fills most of the frame, with only a small amount of negative space to one side. "
    "The face is large and clearly readable — never a distant, small or full-length subject. "
    "{Their_c} waist, legs and feet must be completely out of frame. "
    "Sharp focus on the eyes. Photorealistic, high detail, cinematic colour grading. "
    "Premium collectible character card artwork."
)


# epic 은 스타일링이 주인공이라 얼굴 레퍼런스는 느슨한 참고로만 쓴다.
EPIC_FACE_ROLE = (
    "the FACE reference. Use it only as a LOOSE starting point for the general face type and "
    "impression — the broad shape of the face and the character of the eyes. "
    "Do not match it closely. Apply the deviations listed above in full; the result should read "
    "as a clearly different person who happens to share a similar face type. "
    "Do not take the hair from it — the hair follows the styling reference instead. "
    "Ignore this photo's background, clothing, pose, camera angle, lighting and colour grading, "
    "and any text, watermark or logo on it."
)

EPIC_POSE_ROLE = (
    "the POSE reference. Copy ONLY the body pose from it — the angle of the torso and shoulders, "
    "the position of the arms and hands, the tilt of the head. "
    "Do NOT take the facial expression or the eye direction from it; those are specified "
    "separately above and take priority. "
    "Ignore this photo's person, face, hair, clothing, background, lighting and colour grading "
    "completely."
)

N_DEVIATIONS_EPIC = 5


def ref_instruction(kinds):
    ordinals = ["The first", "The second", "The third"]
    roles = dict(N.REF_ROLE, face=EPIC_FACE_ROLE, pose=EPIC_POSE_ROLE, cosplay=COSPLAY_ROLE)
    if not kinds:
        return ""
    parts = [f"{ordinals[i]} attached photo is {roles[k]}" for i, k in enumerate(kinds)]
    head = (f"{len(kinds)} reference photos are attached, in this order. " if len(kinds) > 1
            else "A reference photo is attached. ")
    return " " + head + " ".join(parts)


def build_prompt(species_key, rng, refs=None, gender=None, face_key=None, add=None):
    gender = gender or "m"
    refs = refs or []
    label, default_face, look, outfit, light = SPECIES[species_key]
    face_key = face_key or default_face
    _, face_desc = N.PRESETS[face_key]

    base = epic_base(gender)
    subj, their = ("She", "her") if gender == "f" else ("He", "his")

    picked = rng.sample(list(N.VARIATIONS), min(N.N_VARIATIONS, len(N.VARIATIONS)))
    micro = [rng.choice(N.VARIATIONS[k]) for k in picked]
    marks = [m for m in (rng.choice(N.MARKS[k]) for k in ("mole", "freckles", "dimple")) if m]
    details = ", ".join(micro + marks)
    marks_rule = f" {N.MARKS_RULE}" if marks else ""

    dev_part = ""
    if "face" in refs or "cosplay" in refs:
        picks = rng.sample(N.DEVIATIONS, N_DEVIATIONS_EPIC)
        dev_part = ("Compared to the person in the attached reference photos, "
                    "this person differs as follows: "
                    + "; ".join(picks) + ". These differences are mandatory. ")

    hair_part = "" if ("face" in refs or "cosplay" in refs) else f"Hair: {rng.choice(N.hair_pool(gender))}. "

    pose_part = ""
    if "pose" not in refs:
        pose_part = f"Pose: {subj.lower()} is {rng.choice(N.POSES)}, {rng.choice(N.ANGLES)}. "
        if gender == "f":
            pose_part = N._fem(pose_part)

    env = ENVIRONMENTS.get(species_key)
    env_part = f"Setting: {subj.lower()} is {env} {ENV_RULE} " if env else ""
    if gender == "m" and env_part:
        env_part = N._fem(env_part).replace(" her ", " his ").replace(" she ", " he ")
    expr_part = f"Expression: {rng.choice(EXPRESSIONS)}. {EXPRESSION_RULE} "
    prop = rng.choice(PROPS.get(species_key, [""]))
    if prop:
        expr_part += (f"{subj} is holding {prop}, brought up near the face — "
                      "it reads as a real object with real weight, lit by the same light. ")
    framing = FRAMING.format(Their_c=their.capitalize())
    ref_part = ref_instruction(refs)
    add_part = f" {add}" if add else ""

    if "cosplay" in refs:
        style_part = ""
    else:
        style_part = (f"Outfit: {outfit}. "
                      f"Lighting and atmosphere: {light}. ")

    return (
        f"{base} {face_desc} "
        f"Individual details: {details}.{marks_rule} "
        f"{dev_part}"
        f"{hair_part}"
        f"{look} {SPECIES_RULE} {COSTUME_RULE} "
        f"{style_part}"
        f"{pose_part}"
        f"{env_part}"
        f"{expr_part}"
        f"{framing} {HOUSE_LOOK} {SKIN_RULE} {PHOTO_RULE}{ref_part}{add_part}"
    )


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
    gender = opt("--gender", "m")
    face_override = opt("--face")
    add = opt("--add")
    want = "" if "--no-ref" in argv else opt("--refs", "pose,cosplay")
    for name in ("--n", "--seed", "--gender", "--face", "--add", "--refs"):
        if name in argv:
            v = argv[argv.index(name) + 1]
            if v in args:
                args.remove(v)

    kinds = [k.strip() for k in want.split(",") if k.strip()]
    if any(k not in REF_KINDS for k in kinds):
        print(f"epic 이 쓰는 레퍼런스: {REF_KINDS}")
        sys.exit(1)

    genders = ["m", "f"] if gender == "both" else [gender]
    if any(g not in N._SUBJECT for g in genders):
        print("성별: m | f | both")
        sys.exit(1)

    keys = args or list(SPECIES)
    bad = [k for k in keys if k not in SPECIES]
    if bad:
        print(f"모르는 종족: {bad}\n사용 가능: {list(SPECIES)}")
        sys.exit(1)

    if face_override and face_override not in N.PRESETS:
        print(f"모르는 얼굴상: {face_override}\n사용 가능: {list(N.PRESETS)}")
        sys.exit(1)

    rng = random.Random(int(seed) if seed else None)

    pools = {}
    for g in genders:
        for k in kinds:
            if k == "face":
                for sk in keys:
                    fk = face_override or SPECIES[sk][1]
                    pools[(g, k, fk)] = N.ref_pool(k, g, fk)
            elif k == "cosplay":
                for sk in keys:
                    pools[(g, k, sk)] = cosplay_pool(g, sk)
            else:
                pools[(g, k, None)] = N.ref_pool(k, g)

    print(f"epic · {ASPECT} · 성별: "
          + ", ".join("남자" if g == "m" else "여자" for g in genders))
    os.makedirs(OUT_DIR, exist_ok=True)
    tok = N.token()
    jobs = [(g, sk, i) for g in genders for sk in keys for i in range(1, n + 1)]

    for idx, (g, sk, i) in enumerate(jobs):
        fk = face_override or SPECIES[sk][1]
        label = SPECIES[sk][0] + (" · 여자" if g == "f" else " · 남자")
        out = os.path.join(OUT_DIR, f"epic_{g}_{sk}_{i:02d}.png")

        used, paths = [], []
        for k in kinds:
            if k == "face":
                pool = pools[(g, k, fk)]
            elif k == "cosplay":
                pool = pools[(g, k, sk)]
            else:
                pool = pools[(g, k, None)]
            if pool:
                used.append(k)
                paths.append(rng.choice(pool))
        tag = (" +" + ",".join(os.path.basename(x) for x in paths)) if paths else ""
        print(f"[{idx+1}/{len(jobs)}] {label} → {os.path.basename(out)}{tag} ... ",
              end="", flush=True)

        prompt = build_prompt(sk, rng, refs=used, gender=g, face_key=fk, add=add)
        err = None
        for attempt in range(N.RETRIES):
            loc = N.LOCATIONS[(idx + attempt) % len(N.LOCATIONS)]
            err = N.generate(prompt, out, tok, loc, ref_paths=paths, aspect=ASPECT)
            if err is None:
                print(f"OK ({loc})")
                break
            if attempt < N.RETRIES - 1:
                print(f"재시도({loc} 실패) ", end="", flush=True)
                time.sleep(N.INTERVAL)
        else:
            print(f"실패 — {err}")
        if idx < len(jobs) - 1:
            time.sleep(N.INTERVAL)

    print(f"\n완료 → {OUT_DIR}")


if __name__ == "__main__":
    main()
