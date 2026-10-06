"""
실사 아이돌 프롬프트 — ~/claude/idol-photos/tools/female_idol.py · male_idol.py (2026-10-07 확정 생성기) 의 사본.

얼굴 · 눈 · 코 · 입 · 미세 특징 · 머리 모양 · 머리색 · 화장 · 포즈는 매번 무작위.
만들기 화면에서 고르는 것은 분위기(vibe) 또는 이종족(race) 하나이고, 관람객이 쓴 문장은 맨 뒤에 붙인다.
원본과 다른 점: 결과를 라벨(2:3 세로)로 쓰므로 비율 문장을 2:3 으로, 최근 색 · 머리 반복 피하기(history 파일)와
이종족 머리띠 지우기 2차 편집 · 노란기 보정 · 업스케일은 하지 않는다(전시장에서 기다리는 시간을 줄이려고).
원본 목록을 고치면 tools 쪽 스크립트에서 다시 뽑아 이 파일을 갱신한다.
"""

D = {'f': {'face': ['soft oval face',
                'small heart-shaped face with a pointed chin',
                'round baby face with full cheeks',
                'slim long-ish oval face with high cheekbones',
                'small V-line face with soft baby cheeks'],
       'eyes': ['big round puppy eyes',
                'sharp upturned cat eyes',
                'MONOLID eyes (mussang, no double eyelid crease)',
                'soft MONOLID droopy eyes (mussang)',
                'inner-fold double eyelids',
                'wide double-lidded doe eyes',
                'narrow cool eyes with subtle inner fold',
                'droopy gentle eyes'],
       'nose': ['small button nose', 'straight slim nose', 'soft rounded nose', 'high defined nose bridge'],
       'lips': ['full plump lips', 'small heart-shaped lips', 'thin elegant lips', 'wide smiling lips'],
       'brows': ['straight soft brows', 'thick natural brows', 'slightly arched thin brows'],
       'vibe': ['cute and bubbly', 'cool and chic', 'innocent and pure', 'bold girl-crush', 'dreamy and soft', 'playful tomboy'],
       'pose': ['head turned in a three-quarter view to the left',
                'head turned in a three-quarter view to the right',
                'body turned sideways, looking back over her shoulder',
                'head tilted and turned to one side',
                'face angled to one side, hands out of frame',
                'chin slightly lowered with the face turned to the side'],
       'expr': ['calm soft expression', 'faint gentle smile', 'soft pout', 'lips slightly parted, soft gaze'],
       'bg': ['pale lavender-grey', 'pale icy blue-white', 'soft lilac-grey', 'very pale mint-blue'],
       'marks': ['light natural freckles across the nose and cheeks',
                 'cute dimples on both cheeks',
                 'a single dimple on one cheek',
                 'a tiny beauty mark under one eye',
                 'a small mole near the lip',
                 'a small mole on one cheek',
                 'baby-fat round cheeks',
                 'a slightly upturned button nose tip',
                 "a defined cupid's bow",
                 'thick natural lashes',
                 'a sharp slim jawline',
                 'puffy natural aegyo-sal'],
       'COLORS': ['soft black',
                  'natural dark brown',
                  'milk-chocolate brown',
                  'soft caramel brown',
                  'ash-beige brown',
                  'milk-tea beige',
                  'pastel honey blonde',
                  'butter-cream blonde',
                  'pale platinum blonde',
                  'pastel baby pink',
                  'pastel peach',
                  'pastel strawberry-milk pink',
                  'pastel apricot orange',
                  'pastel coral',
                  'pastel lavender',
                  'pastel lilac',
                  'pastel baby blue',
                  'pastel sky-blue silver',
                  'pastel mint',
                  'pastel ash grey',
                  'pastel rose-beige',
                  'milk-tea brown with pastel pink ends',
                  'soft brown with pastel lavender underlayer'],
       'STYLES': ['long sleek straight dark hair with wispy piece-y see-through bangs (slightly separated strands) and long face-framing '
                  'layers falling past the cheeks',
                  'two round DANGO buns (space buns) on top of the head with long hair down',
                  'two neat odango buns with all hair up and face-framing strands',
                  'high twin tails (yangalrae pigtails) with see-through bangs',
                  'low twin tails tied with plain ties',
                  'APPLE HAIR (sagwa-meori): ALL the front bangs are pulled straight UP off the forehead and tied into a tiny sprouting '
                  'palm-tree ponytail right above the forehead, forehead fully exposed with NO bangs hanging down, rest of the long hair '
                  'down',
                  'CHOPPY BANGS (short jagged micro bangs) with long straight hair',
                  'choppy uneven short bangs with a shaggy bob',
                  'very long sleek straight hair (gin-saengmeori) with center part',
                  'very long straight hair with blunt full bangs',
                  'SHAGGY layered short bob with messy texture',
                  'shaggy chin-length bob with see-through bangs',
                  'short flipped-out bob',
                  'hime cut with blunt side locks and full bangs',
                  'long loose curly waves with curtain bangs',
                  'high ponytail with face-framing strands',
                  'half-up half-down with a small top knot',
                  'two low braided plaits',
                  'messy wolf cut with layered bangs',
                  'short pixie cut with wispy bangs',
                  'long layered hush cut with side-swept bangs',
                  'half-up twin mini buns with long hair down'],
       'RACES': {'mermaid': 'a MERMAID idol: delicate iridescent pearl-aqua fish scales softly glimmering along her cheekbones, temples, '
                            'neck and shoulders, small translucent fin-shaped ears, a dewy wet-look sheen on the skin',
                 'fairy': 'a FAIRY idol: pointed elf-like ears, large delicate translucent iridescent wings (like dragonfly wings) visible '
                          'behind her shoulders, tiny sparkling glitter freckles on her cheeks',
                 'gumiho': 'a GUMIHO (nine-tailed fox) idol: soft fluffy fox ears on top of her head in the same color as her hair, '
                           'slightly sly upturned fox eyes',
                 'unicorn': 'a UNICORN idol: a small elegant pearlescent spiral horn on her forehead, softly shimmering opalescent '
                            'highlights in her hair like a mane, faint glitter on her cheekbones',
                 'butterfly': 'a BUTTERFLY-insect idol: large pastel patterned butterfly wings behind her shoulders, two thin delicate '
                              'antennae rising from her hair, faint wing-pattern shimmer on the outer corners of her eyes',
                 'moth': 'a MOTH-insect idol: soft fuzzy feathered moth antennae on her head, large velvety pale moth wings behind her, a '
                         'soft fluffy fur collar texture at her neck',
                 'bee': 'a BEE-insect idol: two small antennae with tiny round tips on her head, small translucent bee wings behind her, '
                        'faint honey-gold shimmer on her cheeks',
                 'elf': 'an ELF idol: naturally long slender pointed ears growing from her head and partly tucked through her hair, an '
                        'ethereal otherworldly glow to her skin',
                 'angel': 'an ANGEL idol: large soft white feathered wings behind her shoulders, a faint glowing halo light above her head',
                 'dragon': 'a DRAGON idol: small elegant curved horns on her head, a few pearlescent dragon scales on her cheekbones and '
                           'neck, slit-pupil reptilian eyes',
                 'cat': 'a CAT-beast idol: soft cat ears on top of her head matching her hair color, faintly feline eyes',
                 'rabbit': 'a RABBIT-beast idol: two separate real biological rabbit ears, each one growing individually out of her scalp '
                           'at two distinct points on the upper sides of her head, with her own hair strands parting and falling naturally '
                           'around each ear base so the roots are hidden in the hair (she has NO human ears) — thin ear leather covered in '
                           'short dense natural rabbit fur in a natural rabbit color (white, cream, light grey or soft brown), fine '
                           'visible blood vessels and light shining through the thin pink inner ear, like a real live rabbit in a nature '
                           'photograph',
                 'vampire': 'a VAMPIRE idol: very pale porcelain skin, faint crimson-tinted irises, tiny delicate fangs visible when her '
                            'lips part',
                 'tiger': 'a TIGER-beast idol: round fluffy tiger ears on top of her head with orange fur, black stripes and white inner '
                          'fur, faint soft tiger stripe markings at her temples and along her neck, golden amber eyes with a fierce gaze',
                 'fish': "a FISH-folk idol: delicate translucent fan-shaped fins in place of ears, flowing like a betta fish's fins in "
                         'soft pastel gradient, a few small glossy iridescent scales along her cheekbones, jaw and collarbones, faint gill '
                         'lines on the sides of her neck',
                 'deer': 'a DEER-spirit idol: two slender real deer antlers (like a young sika deer, a few elegant tines, natural '
                         'bone-and-velvet texture in soft beige-brown) growing directly out of her scalp just above the hairline on each '
                         'side, the bases hidden in her hair; she has normal human ears; no deer ears, no fur, no flowers'},
       'COLOR_NOTE_T': 'The hair is clearly and recognizably {color} (its hue must be obvious, NOT grey, NOT silver unless named), in a '
                       'soft milky pastel shade — never vivid, never neon.',
       'PEACH': 'clean bright fair porcelain skin with no yellow undertone; very LIGHT soft eye makeup — natural eyelids, natural lashes, '
                'no heavy liner, nothing dark or smoky around the eyes; naturally defined soft brows; a sheer APRICOT-PEACH under-eye '
                'blush softly placed right below the eyes on the aegyo-sal and upper cheeks; emphasized puffy aegyo-sal with a soft '
                'highlight; all makeup colors are apricot / peach tones, NOT pink, NOT red',
       'lips_mk': ['muted dusty peach overlined lips with a soft sheer gloss',
                   'muted milky apricot-beige overlined lips with light gloss',
                   'soft toned-down nude-peach overlined lips with a subtle glossy sheen'],
       'lips_note': ' (low saturation, muted, never bright, never vivid coral or red)'},
 'm': {'face': ['small oval face',
                'slim long face',
                'soft round face',
                'small face with defined cheekbones',
                'heart-shaped face with a pointed chin',
                'short compact face'],
       'eyes': ['big round puppy eyes',
                'sharp upturned cat eyes',
                'MONOLID eyes (mussang, no double eyelid crease)',
                'soft MONOLID droopy eyes (mussang)',
                'inner-fold double eyelids',
                'wide double-lidded doe eyes',
                'narrow cool eyes with subtle inner fold',
                'droopy gentle eyes'],
       'nose': ['small button nose', 'straight slim nose', 'soft rounded nose tip', 'high sharp nose bridge', 'aquiline refined nose'],
       'lips': ['full plump lips',
                'thin lips',
                "heart-shaped lips with a defined cupid's bow",
                'small soft lips',
                'slightly pouty upper lip'],
       'brows': ['thick straight brows', 'soft thin brows', 'naturally arched brows', 'short straight brows'],
       'vibe': ['boyish and bright',
                'cool and chic',
                'soft and gentle',
                'dreamy and soft',
                'charismatic and intense',
                'playful puppy-like'],
       'pose': ['head turned in a three-quarter view to the left',
                'head turned in a three-quarter view to the right',
                'body turned sideways, looking back over his shoulder',
                'head tilted and turned to one side',
                'face angled to one side, hands out of frame',
                'chin slightly lowered with the face turned to the side'],
       'expr': ['calm soft expression', 'faint gentle smile', 'soft pout', 'lips slightly parted, soft gaze'],
       'bg': ['pale lavender-grey', 'pale icy blue-white', 'soft lilac-grey', 'very pale mint-blue'],
       'marks': ['light natural freckles across the nose and cheeks',
                 'dimples on both cheeks',
                 'a single dimple on one cheek',
                 'a tiny beauty mark under one eye',
                 'a small mole near the lip',
                 'a small mole on one cheek',
                 'a slightly upturned nose tip',
                 'thick natural lashes',
                 'puffy natural aegyo-sal',
                 'a high slim nose bridge'],
       'COLORS': ['soft black',
                  'natural dark brown',
                  'milk-chocolate brown',
                  'soft caramel brown',
                  'ash-beige brown',
                  'milk-tea beige',
                  'pastel honey blonde',
                  'butter-cream blonde',
                  'pale platinum blonde',
                  'pastel baby pink',
                  'pastel peach',
                  'pastel strawberry-milk pink',
                  'pastel apricot orange',
                  'pastel coral',
                  'pastel lavender',
                  'pastel lilac',
                  'pastel baby blue',
                  'pastel sky-blue silver',
                  'pastel mint',
                  'pastel ash grey',
                  'pastel rose-beige',
                  'milk-tea brown with pastel pink ends',
                  'soft brown with pastel lavender underlayer'],
       'STYLES': ['FOREHEAD-EXPOSED up-styled hair (bangs pushed up and back, full forehead visible)',
                  '6:4 side-parted GAEIL hair (bangs swept to one side in a big soft curve, forehead partly visible)',
                  'LONG hair reaching past the shoulders, loose and straight with a center part',
                  'shoulder-length hair tied in a small low half-ponytail, loose strands framing the face',
                  'big voluminous CURLY perm (tight curls all over) with curly bangs',
                  'MULLET: short on top and sides, long tail of hair down the back of the neck, wispy bangs',
                  'messy wavy jaw-length hair with long bangs fully covering the eyes',
                  'very SHORT crop with tiny micro bangs, ears and neck fully visible',
                  'WET-LOOK slicked-back hair, forehead fully exposed',
                  'fluffy wolf cut with long choppy layers at the nape and piece-y bangs',
                  'middle-part curtain bangs, chin-length hair tucked behind both ears',
                  'soft comma hair (one side of the bangs curled into a comma shape, the other side up)'],
       'RACES': {'mermaid': 'a MERMAID idol: delicate iridescent pearl-aqua fish scales softly glimmering along his cheekbones, temples, '
                            'neck and shoulders, small translucent fin-shaped ears, a dewy wet-look sheen on the skin',
                 'fairy': 'a FAIRY idol: pointed elf-like ears, large delicate translucent iridescent wings (like dragonfly wings) visible '
                          'behind his shoulders, tiny sparkling glitter freckles on his cheeks',
                 'gumiho': 'a GUMIHO (nine-tailed fox) idol: soft fluffy fox ears on top of his head in the same color as his hair, '
                           'slightly sly upturned fox eyes',
                 'unicorn': 'a UNICORN idol: a small elegant pearlescent spiral horn on his forehead, softly shimmering opalescent '
                            'highlights in his hair like a mane, faint glitter on his cheekbones',
                 'butterfly': 'a BUTTERFLY-insect idol: large pastel patterned butterfly wings behind his shoulders, two thin delicate '
                              'antennae rising from his hair, faint wing-pattern shimmer on the outer corners of his eyes',
                 'moth': 'a MOTH-insect idol: soft fuzzy feathered moth antennae on his head, large velvety pale moth wings behind him, a '
                         'soft fluffy fur collar texture at his neck',
                 'bee': 'a BEE-insect idol: two small antennae with tiny round tips on his head, small translucent bee wings behind him, '
                        'faint honey-gold shimmer on his cheeks',
                 'elf': 'an ELF idol: naturally long slender pointed ears growing from his head and partly tucked through his hair, an '
                        'ethereal otherworldly glow to his skin',
                 'angel': 'an ANGEL idol: large soft white feathered wings behind his shoulders, a faint glowing halo light above his head',
                 'dragon': 'a DRAGON idol: small elegant curved horns on his head, a few pearlescent dragon scales on his cheekbones and '
                           'neck, slit-pupil reptilian eyes',
                 'cat': 'a CAT-beast idol: soft cat ears on top of his head matching his hair color, faintly feline eyes',
                 'rabbit': 'a RABBIT-beast idol: two separate real biological rabbit ears, each one growing individually out of his scalp '
                           'at two distinct points on the upper sides of his head, with his own hair strands parting and falling naturally '
                           'around each ear base so the roots are hidden in the hair (he has NO human ears) — thin ear leather covered in '
                           'short dense natural rabbit fur in a natural rabbit color (white, cream, light grey or soft brown), fine '
                           'visible blood vessels and light shining through the thin pink inner ear, like a real live rabbit in a nature '
                           'photograph',
                 'vampire': 'a VAMPIRE idol: very pale porcelain skin, faint crimson-tinted irises, tiny delicate fangs visible when his '
                            'lips part',
                 'tiger': 'a TIGER-beast idol: round fluffy tiger ears on top of his head with orange fur, black stripes and white inner '
                          'fur, faint soft tiger stripe markings at his temples and along his neck, golden amber eyes with a fierce gaze',
                 'fish': "a FISH-folk idol: delicate translucent fan-shaped fins in place of ears, flowing like a betta fish's fins in "
                         'soft pastel gradient, a few small glossy iridescent scales along his cheekbones, jaw and collarbones, faint gill '
                         'lines on the sides of his neck',
                 'deer': 'a DEER-spirit idol: two slender real deer antlers (like a young sika deer, a few elegant tines, natural '
                         'bone-and-velvet texture in soft beige-brown) growing directly out of his scalp just above the hairline on each '
                         'side, the bases hidden in his hair; he has normal human ears; no deer ears, no fur, no flowers'},
       'COLOR_NOTE_T': 'The hair is clearly and recognizably {color} (its hue must be obvious, NOT grey unless named), in a soft milky '
                       'pastel or natural shade — never vivid, never neon.',
       'PEACH': 'clean bright fair skin with a natural satin finish and no yellow undertone; minimal male idol grooming makeup — natural '
                'groomed brows, almost no eye makeup, a very faint warm peach flush on the cheeks and nose tip, subtle aegyo-sal; colors '
                'are soft peach / natural tones, NOT pink, NOT red',
       'lips_mk': ['muted natural peach-nude lips with a soft sheen',
                   'soft rosy-beige tinted lips',
                   'natural MLBB peach lips with light balm'],
       'lips_note': ' (low saturation, muted, never bright)',
       'archetype': ['PUPPY-face (gangaji-sang): round droopy gentle eyes, soft rounded features, warm innocent look',
                     'CAT-face (goyangi-sang): sharp upturned almond eyes, sleek angular cheekbones, aloof chic look',
                     'FOX-face (yeou-sang): narrow elongated upturned eyes, slim pointed chin, sly charismatic look',
                     'BUNNY-face (tokki-sang): big round bright eyes, slightly prominent front teeth, small mouth, cute bright look',
                     'DEER-face (sasum-sang): large clear doe eyes with long lashes, long slim neck, pure delicate look',
                     'BEAR-face (gom-sang): soft kind eyes and a cozy warm gentle look',
                     'DINOSAUR-face (gongryong-sang): sharp straight brows and a striking intense gaze',
                     'CHIC MONOLID face: long narrow monolid eyes, straight nose, thin lips, cool minimalist look',
                     'PRINCE face: refined elegant features, high nose bridge, defined double eyelids, noble look',
                     'SUNNY BOY face: wide bright smile lines, crescent eye-smile, energetic friendly look'],
       'MESSY': ['long messy wavy fluffy hair down to the jaw/neck, tousled and slightly frizzy, long bangs falling over one eye',
                 'messy wavy mullet-like hair with lots of fluffy volume, long piece-y bangs covering the brows and eyes, strands sticking '
                 'out',
                 'shaggy unkempt fluffy layers to the nape, airy bedhead texture, bangs messily covering half of the face'],
       'BLACKS': ['jet black', 'soft natural black']}}

# 만들기 화면에 보이는 이름 (create.js 와 같은 키)
VIBES = {
    "f": {"cute and bubbly": "발랄", "cool and chic": "시크", "innocent and pure": "청순",
          "bold girl-crush": "걸크러시", "dreamy and soft": "몽환", "playful tomboy": "보이시"},
    "m": {"boyish and bright": "청량", "cool and chic": "시크", "soft and gentle": "다정",
          "dreamy and soft": "몽환", "charismatic and intense": "카리스마", "playful puppy-like": "댕댕"},
}
RACE_KEYS = ["mermaid", "fairy", "gumiho", "elf", "angel", "cat", "rabbit", "tiger", "vampire", "dragon", "butterfly"]


def build_prompt(gender, rng, vibe=None, race=None, add=None):
    g = "m" if gender == "m" else "f"
    d = D[g]
    she, her, Her = ("he", "his", "His") if g == "m" else ("she", "her", "Her")
    R = rng
    face = R.choice(d["face"]); eyes = R.choice(d["eyes"]); nose = R.choice(d["nose"])
    lips = R.choice(d["lips"]); brows = R.choice(d["brows"])
    mark = ", ".join(R.sample(d["marks"], R.choice([0, 1, 1, 2, 2]))) or "clear skin"
    if "single dimple" in mark and "both cheeks" in mark:
        mark = mark.replace(", a single dimple on one cheek", "").replace("a single dimple on one cheek, ", "")
    if g == "m":
        color = R.choice(d["BLACKS"]) if R.random() < 0.55 else R.choice(d["COLORS"])
        style = R.choice(d["MESSY"]) if R.random() < 0.4 else R.choice(d["STYLES"])
    else:
        color = R.choice(d["COLORS"]); style = R.choice(d["STYLES"])
    color_note = d["COLOR_NOTE_T"].format(color=color)
    bare = R.random() < (0.25 if g == "m" else 0.2)
    makeup = ("completely BARE FACE, no makeup at all — natural fresh clean skin with real skin texture, natural brows, no blush, "
              "no eyeliner, no lipstick; pure natural beauty, no yellow undertone") if bare else d["PEACH"]
    lipc = "natural bare lips with only a little clear lip balm" if bare else R.choice(d["lips_mk"]) + d["lips_note"]
    vibe = vibe if vibe in VIBES[g] else R.choice(d["vibe"])
    pose = R.choice(d["pose"]); expr = R.choice(d["expr"])
    if "dimple" in mark:
        expr = "a sweet smile that clearly shows the dimples"
    bg = R.choice(d["bg"])
    angle = ("The face is clearly ANGLED / TURNED — NEVER a straight-on frontal face, never a symmetrical passport-style pose, "
             "never facing the lens squarely. ")
    race_txt = ""
    if race in d["RACES"]:
        race_txt = (f"FANTASY SPECIES: {she} is {d['RACES'][race]}. These fantasy features are a natural, living part of {her} body — "
                    f"seamlessly grown, same skin tone and texture where they meet {her} skin, photorealistic and high-end like a big-budget "
                    f"K-pop concept photo; NOT prosthetics, absolutely NO headband, NO hairband, NO band or strip of fur across the top of "
                    f"the head connecting the ears, nothing worn on the head — the top of {her} head is just {her} natural hair, NOT cosplay, "
                    f"NOT a cheap costume. The features are clearly visible in the frame. NO tail of any kind. Any fur must look like REAL "
                    f"living animal fur and skin as in macro wildlife photography — short dense natural hairs, natural sheen, real anatomy "
                    f"and translucency — NOT plush, NOT faux fur, NOT a stuffed toy, NOT felt. Animal-eared species have no human ears. ")
    if g == "m":
        arch = R.choice(d["archetype"])
        head = ("High-end K-pop boy-group idol concept photo of a fictional Korean male idol with top-tier idol VISUALS — the 'visual center' "
                "of a famous boy group, an extremely handsome FLOWER-BOY (kkonminam) — breathtakingly pretty, delicate, almost androgynous "
                f"beauty like the most beautiful visual members of top K-pop boy groups, with a subtle hint of {arch} so his face is his own "
                "(beauty comes first, the face type is only a light nuance); tiny face, clear sparkling eyes, high slim nose bridge, short "
                "narrow chin, slim V-line jaw (never wide, square or heavy), flawless porcelain glass skin, slender neck and slim narrow "
                "shoulders, slender build; boyish and youthful, around 20-21 years old (an adult), never looks older than 22, NO mature or "
                f"rugged manly features, star aura, {vibe} vibe. "
                "Professionally styled by an idol hair and makeup team, glossy salon-perfect hair, polished camera-ready idol grooming. ")
        face_txt = f"FACE: {face}, {brows}, {nose}, {lips}, {mark} (eye shape follows the face type above). "
    else:
        head = ("High-end K-pop girl-group idol concept photo of a fictional Korean female idol with top-tier idol VISUALS — the 'visual "
                "center' of a famous girl group, strikingly beautiful, flawless doll-like features, tiny face, perfect proportions, star "
                f"aura, clearly an adult woman in her early twenties, {vibe} vibe. "
                "Professionally styled by an idol hair and makeup team, glossy salon-perfect hair, polished camera-ready idol makeup. ")
        face_txt = f"FACE: {face}, {eyes}, {nose}, {mark}. "
    prompt = (head +
              "Unique face, must NOT resemble any real celebrity. Not an ordinary person, not a casual snapshot. Tasteful, non-sexual. " +
              race_txt + face_txt +
              f"HAIRSTYLE (important — follow this exact cut and shape): {style}. HAIR COLOR: {color}. {color_note} "
              f"MAKEUP: {makeup}, {lipc}. NO earrings, no ear piercings, no jewelry at all, bare ears. "
              "Outfit: a plain basic white short-sleeve crew-neck t-shirt with the sleeves rolled up, nothing else. "
              f"POSE: {pose}, {expr}. Hands are not in the frame, no hand gestures. {Her} EYES look DIRECTLY INTO THE CAMERA "
              f"(eye contact with the viewer). {angle}Chest-up portrait framing. "
              "LIGHTING: soft, even, bright FRONTAL studio beauty light (large softbox near the camera), clean and flattering, very few "
              "shadows, fresh luminous skin, crisp sharp focus, natural colors, NOT overexposed, NOT washed out. "
              f"Plain {bg} solid seamless background, evenly lit. "
              "Clean pure photograph: NO handheld props, NO text, NO logo, NO watermark. Vertical 2:3 portrait.")
    if add:
        prompt += f" Additional requests from the creator (follow them, they override the random choices above): {add}"
    return prompt
