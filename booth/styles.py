"""변환 스타일. 키·이름은 apps_script/Code.gs의 STYLES, apps_script/index.html의 STYLES와 같아야 한다(테스트가 확인).

특정 회사·작품 이름(○○ 스튜디오풍 등)은 넣지 않고 재료·기법으로만 설명한다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    key: str
    label: str
    prompt: str
    backdrop: str


STYLES: dict[str, Style] = {s.key: s for s in [
    Style("felt", "양모펠트 인형",
          "a handmade needle-felted wool figure photographed in a soft-lit studio: fuzzy wool fibre texture with tiny "
          "visible fibres, soft rounded felted shapes, small shiny bead eyes, shallow depth of field",
          "warm pastel studio backdrop"),
    Style("clay", "클레이 인형",
          "a stop-motion plasticine clay figure: smooth hand-sculpted clay with subtle fingerprints and tool marks, "
          "slightly glossy surface, soft studio lighting",
          "simple miniature clay set backdrop"),
    Style("anime2d", "2D 애니메이션",
          "a 2D cel-shaded TV animation character: clean bold outlines, flat bright colours with simple two-tone "
          "shading, big expressive eyes, like a frame from a modern children's animated series",
          "simple soft-colour animated background"),
    Style("anim3d", "3D 애니메이션",
          "a 3D animated feature-film character render: appealing rounded shapes, big expressive eyes, soft global "
          "illumination and subsurface lighting, detailed but simple materials",
          "soft blurred cinematic background"),
    Style("plush", "봉제 인형",
          "a soft plush toy sewn from fabric: minky and felt fabric textures, visible stitched seams, embroidered "
          "eyes, stuffed rounded body, cosy product photo",
          "soft plain fabric backdrop"),
    Style("pixel", "픽셀아트 게임",
          "a retro 16-bit pixel-art video game character sprite: crisp square pixels, limited bright palette, clean "
          "readable silhouette, shown large",
          "simple pixel-art game scenery backdrop"),
    Style("watercolor", "수채화 그림책",
          "a children's picture-book watercolour illustration: soft watercolour washes, gentle coloured-pencil "
          "lines, visible paper texture, warm and dreamy",
          "light watercolour paper background"),
    Style("sticker", "스티커",
          "a cute die-cut sticker: chibi proportions, bold clean outline, glossy flat vector colours, a thick white "
          "border all around the character",
          "plain very light grey background"),
]}

NOT_A_DRAWING = "NOT_A_DRAWING"

PROMPT = """You are turning a child's hand-drawn original character into a finished character illustration for a school
booth activity. The attached photo shows the child's drawing, usually on a printed worksheet.

Step 1. Look at the attached photo. If it does not show a hand-drawn character (for example it is a photo of a real
person or a real face, a blank page, or something not suitable for children), do NOT generate anything and reply with
exactly: {not_a_drawing}

Step 2. Otherwise, create ONE image with your built-in image generation tool, using the attached photo as the
reference image. Keep the child's design clearly recognisable: the same kind of character, body shape and
proportions, colours, clothes, accessories, facial expression and every distinctive detail the child drew. Do not
replace it with a different or more generic character, and do not add other characters. Ignore the worksheet's
printed text, lines, boxes and the paper itself.

Style: {style}.
{intro}Composition: one single full-body character, centred, facing the viewer, on a {backdrop}. Square image (1:1,
1024x1024). Cute, cheerful and child-friendly.
Absolutely no text, letters, numbers, speech bubbles, logos or watermark anywhere in the image.

After it is generated, STOP. Do not move, copy, rename, save, or relocate the file, and do not run any shell command
to find it. Leave it in your default generated-images directory; it will be collected automatically."""


def clean_intro(text: str) -> str:
    """아이가 적은 소개(취미·특기)는 그림 힌트로만 쓴다. 따옴표·줄바꿈·지시처럼 보이는 기호를 지우고 60자로 자른다."""
    text = " ".join(str(text or "").split())
    text = "".join(ch for ch in text if ch not in '"`{}<>[]\\')
    return text[:60]


def build_prompt(style_key: str, intro: str = "") -> str:
    style = STYLES[style_key]
    intro = clean_intro(intro)
    intro_line = (f'About the character, written by the child (may be Korean; use only as small visual hints such '
                  f'as a prop or pose, never as text in the image): "{intro}"\n') if intro else ""
    return PROMPT.format(not_a_drawing=NOT_A_DRAWING, style=style.prompt, backdrop=style.backdrop, intro=intro_line)
