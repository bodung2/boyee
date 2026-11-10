"""장소 글(아이와 가볼 곳): places_inbox 폴더의 사진·메모를 글감으로 준비한다.

places_inbox\\
  국립과천과학관\\        ← 장소마다 폴더 하나(폴더 이름은 아무거나)
    메모.txt              ← 다녀온 날·아이 반응·좋았던/아쉬웠던 점·꿀팁(아무 형식이나 괜찮다)
    IMG_1234.jpg …        ← 직접 찍은 사진 3장 이상(jpg·png·heic·webp)
  _발행됨\\               ← 발행이 끝난 폴더가 'YYYY-MM-DD 폴더이름'으로 옮겨진다

사진은 올리기 전에 반드시 이 모듈을 거친다.
- 위치 정보(GPS)·촬영 기기 같은 사진 속 정보(EXIF)를 모두 지운다(새로 저장할 때 EXIF를 붙이지 않음).
- 얼굴을 찾아 흐리게 만든다(OpenCV의 YuNet 모델 + 옛 방식 Haar, 둘 중 하나라도 찾으면 흐림).
  얼굴 찾기를 쓸 수 없으면 사진을 올리지 않고 멈춘다(안전한 쪽으로 실패).
- 긴 변을 1600px로 줄인다.
얼굴 찾기가 놓친 얼굴·명찰·차 번호판은 검수 단계(childhood-place-factcheck)가 사진을 직접 보고 한 번 더 걸러 낸다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

log = logging.getLogger(__name__)

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
DONE_DIR = "_발행됨"
EXAMPLE_MEMO = "_메모_예시.txt"
MIN_PHOTOS = 3            # 폴더에 이만큼은 있어야 글을 쓴다
MAX_PHOTOS = 15           # 글에 쓸 후보로 넘기는 최대 장수(촬영 순서대로 앞에서부터)
MIN_MEMO_CHARS = 40       # 메모가 이보다 짧으면 사람 냄새 나는 글을 쓸 수 없다
SETTLE_SEC = 600          # 폴더 속 파일이 마지막으로 바뀐 뒤 이만큼 지나야 쓴다(복사 중인 폴더 방지)
LONG_SIDE = 1600
_DATETIME_ORIGINAL = 36867
_EXIF_IFD = 0x8769

EXAMPLE_TEXT = """이 파일은 예시입니다(이름이 _로 시작하는 파일·폴더는 글감으로 쓰지 않습니다).

[쓰는 법]
1. places_inbox 안에 장소마다 폴더를 하나 만듭니다. 예) places_inbox\\국립과천과학관
2. 그 폴더에 직접 찍은 사진 3장 이상과 메모.txt를 넣습니다.
3. 그날 저녁 예약 작업이 글을 써서 유아 블로그 '아이와 가볼 곳' 카테고리에 올리고,
   폴더를 _발행됨 으로 옮깁니다. 하루에 한 곳씩, 먼저 넣은 폴더부터 올립니다.

[메모.txt 예시 — 아무 형식이나 괜찮고, 짧은 말투 그대로 적어도 됩니다]
장소: 국립과천과학관
다녀온 날: 2026-10-18(토), 오전 10시~오후 2시
누구와: 첫째(6살), 둘째(4살)
제일 좋아한 것: 첫째는 천체투영관, 둘째는 유아체험관 물놀이 코너. 둘째가 나오기 싫다고 울었음
아이가 한 말: "아빠 별이 진짜 머리 위로 지나가!"
아쉬웠던 점: 주말 11시쯤 유아체험관 대기 40분. 식당 줄도 김
꿀팁: 유아체험관은 홈페이지 회차 예약 먼저. 여벌 옷 꼭. 주차장은 10시 전에 가야 여유
한 줄 평: 4~7살이면 반나절 코스로 딱. 재방문 의사 있음

[적으면 좋은 것]
- 아이가 실제로 한 말, 표정, 의외였던 순간(이게 글에서 사람 냄새가 나는 부분입니다)
- 솔직한 아쉬운 점(장점만 있는 글은 광고처럼 보입니다)
- 우리 가족만 아는 꿀팁(시간대·동선·준비물)

[적지 말 것]
- 아이 이름, 어린이집·학교 이름, 사는 동네(글에서도 '첫째·둘째'로만 씁니다)

[사진]
- 동선 순서대로 찍은 사진이 좋습니다(촬영 시각 순서로 정리합니다).
- 위치 정보는 자동으로 지우고, 얼굴은 자동으로 흐리게 처리합니다.
  그래도 아이 얼굴이 크게 나온 사진보다 뒷모습·손·풍경·시설 사진이 안전합니다.
"""


class PhotoError(RuntimeError):
    """사진을 안전하게 준비하지 못했다(얼굴 흐림 도구 없음, 쓸 수 있는 사진 부족 등)."""


@dataclass
class Folder:
    path: Path
    memo: Path | None
    photos: list[Path]
    problems: list[str]

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def ready(self) -> bool:
        return not self.problems

    @property
    def key(self) -> str:
        """발행 이력에 남기는 폴더 표식(폴더 이름 + 메모 내용). 같은 장소를 다시 다녀와 같은 이름으로 넣어도 메모가 다르면 새 글이다."""
        memo = read_memo(self.memo) if self.memo and self.memo.exists() else ""
        return f"{self.name}#{hashlib.sha1(memo.strip().encode('utf-8')).hexdigest()[:10]}"


def ensure_inbox(root: Path) -> None:
    """처음 실행할 때 places_inbox와 메모 예시를 만들어 둔다."""
    root.mkdir(parents=True, exist_ok=True)
    (root / DONE_DIR).mkdir(exist_ok=True)
    example = root / EXAMPLE_MEMO
    if not example.exists():
        example.write_text(EXAMPLE_TEXT, encoding="utf-8")


def _memo_file(folder: Path) -> Path | None:
    txts = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".txt"
                  and not p.name.startswith(("_", ".")))
    named = [p for p in txts if p.stem.strip() in ("메모", "memo")]
    return (named or txts or [None])[0]


def _photo_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_EXT
                  and not p.name.startswith(("_", ".")))


def _last_change(folder: Path) -> float:
    times = [folder.stat().st_mtime] + [p.stat().st_mtime for p in folder.iterdir() if p.is_file()]
    return max(times)


def inspect(folder: Path, now: float | None = None) -> Folder:
    now = time.time() if now is None else now
    memo, photos = _memo_file(folder), _photo_files(folder)
    problems = []
    if memo is None:
        problems.append("메모.txt가 없습니다")
    else:
        text = read_memo(memo)
        if len(text.strip()) < MIN_MEMO_CHARS:
            problems.append(f"메모가 너무 짧습니다({len(text.strip())}자, {MIN_MEMO_CHARS}자 이상: 아이 반응·아쉬운 점·꿀팁)")
    if len(photos) < MIN_PHOTOS:
        problems.append(f"사진이 {len(photos)}장입니다({MIN_PHOTOS}장 이상 필요)")
    if now - _last_change(folder) < SETTLE_SEC:
        problems.append("방금 바뀐 폴더라 다음 실행 때 씁니다(사진 복사 중일 수 있음)")
    return Folder(folder, memo, photos, problems)


def pending(root: Path, now: float | None = None) -> list[Folder]:
    """아직 발행하지 않은 장소 폴더들(먼저 만든 폴더부터)."""
    if not root.exists():
        return []
    dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(("_", "."))]
    dirs.sort(key=lambda d: (d.stat().st_ctime, d.name))
    return [inspect(d, now) for d in dirs]


def pick(root: Path, now: float | None = None) -> tuple[Folder | None, list[Folder]]:
    """오늘 쓸 폴더 하나와, 준비가 덜 된 폴더들(알림용)."""
    folders = pending(root, now)
    ready = [f for f in folders if f.ready]
    waiting = [f for f in folders if not f.ready]
    return (ready[0] if ready else None), waiting


def read_memo(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "utf-16"):       # 윈도우 메모장 옛 저장 방식(ANSI=cp949)도 읽는다
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- 사진 처리

def _register_heif() -> bool:
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        return True
    except ImportError:
        return False


def _taken_at(img: Image.Image) -> str:
    try:
        exif = img.getexif()
        value = exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL) or exif.get(306)
        return str(value or "").strip()
    except Exception:  # noqa: BLE001 - 촬영 시각이 없으면 파일 이름 순서로
        return ""


# YuNet: OpenCV 공식 얼굴 찾기 모델(MIT, opencv_zoo). 작은 얼굴·옆얼굴도 잘 찾는다. 처음 한 번 받아 두고 해시로 확인한다.
YUNET_FILE = "face_detection_yunet_2023mar.onnx"
YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/"
             + YUNET_FILE)
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_SCORE = 0.6          # 낮을수록 더 많이 흐린다(놓치는 것보다 더 흐리는 쪽이 안전)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yunet_model(models_dir: Path) -> Path | None:
    """YuNet 모델 파일. 없으면 받는다. 받지 못하거나 해시가 다르면 None(옛 방식 얼굴 찾기만 쓴다)."""
    path = models_dir / YUNET_FILE
    if path.exists() and _sha256(path) == YUNET_SHA256:
        return path
    try:
        import urllib.request
        models_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(YUNET_URL, timeout=60) as resp:
            tmp.write_bytes(resp.read())
        if _sha256(tmp) != YUNET_SHA256:
            tmp.unlink(missing_ok=True)
            raise ValueError("받은 파일의 해시가 다릅니다")
        tmp.replace(path)
        log.info("얼굴 찾기 모델(YuNet)을 받았습니다: %s", path)
        return path
    except Exception as e:  # noqa: BLE001 - 인터넷이 안 되면 옛 방식(Haar)만으로 흐린다
        log.warning("얼굴 찾기 모델(YuNet)을 받지 못해 옛 방식으로만 찾습니다: %s", e)
        return None


def _load_cascade(cv2, path: Path):
    """옛 방식(Haar) 얼굴 찾기 파일을 메모리로 읽는다(한글 경로에서도 열리게). 못 읽으면 None."""
    try:
        fs = cv2.FileStorage(path.read_text(encoding="utf-8"), cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY)
        cascade = cv2.CascadeClassifier()
        if cascade.read(fs.getFirstTopLevelNode()) and not cascade.empty():
            return cascade
    except Exception as e:  # noqa: BLE001
        log.warning("얼굴 찾기 파일을 읽지 못했습니다(%s): %s", path.name, e)
    return None


class FaceFinder:
    """두 가지 얼굴 찾기(YuNet + Haar)를 모두 돌려 하나라도 찾은 곳은 흐린다."""

    def __init__(self, models_dir: Path | None = None):
        try:
            import cv2
        except ImportError as e:
            raise PhotoError("얼굴 흐림에 필요한 OpenCV가 설치되지 않아 사진을 올리지 않았습니다. "
                             "`.venv\\Scripts\\python.exe -m pip install -r requirements.txt`를 실행하세요.") from e
        self.cv2 = cv2
        # 윈도우의 OpenCV는 한글이 든 경로(C:\\Users\\박보영\\...)의 파일을 열지 못한다.
        # 그래서 파일은 파이썬으로 읽고, OpenCV에는 내용(메모리)만 넘긴다.
        self.cascades: list[tuple[object, bool]] = []      # (얼굴 찾기, 옆얼굴용인지)
        if hasattr(cv2, "CascadeClassifier"):
            base = Path(cv2.data.haarcascades)
            for name, profile in (("haarcascade_frontalface_default.xml", False),
                                  ("haarcascade_frontalface_alt2.xml", False),
                                  ("haarcascade_profileface.xml", True)):
                cascade = _load_cascade(cv2, base / name)
                if cascade is not None:
                    self.cascades.append((cascade, profile))
        self.yunet = None
        model = yunet_model(models_dir) if models_dir and hasattr(cv2, "FaceDetectorYN") else None
        if model:
            try:
                import numpy as np
                self.yunet = cv2.FaceDetectorYN.create(
                    "onnx", np.frombuffer(model.read_bytes(), np.uint8), np.array([], np.uint8),
                    (320, 320), YUNET_SCORE, 0.3, 5000)
            except Exception as e:  # noqa: BLE001 - 모델을 못 읽으면 옛 방식만으로 흐린다
                log.warning("얼굴 찾기 모델(YuNet)을 읽지 못해 옛 방식으로만 찾습니다: %s", str(e).strip()[-200:])
        log.info("얼굴 찾기: YuNet %s, 옛 방식 %d개", "사용" if self.yunet is not None else "없음", len(self.cascades))
        if not self.cascades and self.yunet is None:
            raise PhotoError("얼굴 찾기 도구(OpenCV 얼굴 찾기 파일·YuNet 모델)를 쓸 수 없어 사진을 올리지 않았습니다. "
                             "`.venv\\Scripts\\python.exe -m pip install -r requirements.txt`를 실행하세요.")

    def find(self, img: Image.Image) -> list[tuple[int, int, int, int]]:
        import numpy as np

        cv2 = self.cv2
        rgb = np.array(img.convert("RGB"))
        h, w = rgb.shape[:2]
        boxes: list[tuple[int, int, int, int]] = []
        if self.yunet is not None:
            self.yunet.setInputSize((w, h))
            _, found = self.yunet.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            for row in (found if found is not None else []):
                x, y, fw, fh = (int(v) for v in row[:4])
                boxes.append((max(0, x), max(0, y), fw, fh))
        if self.cascades:
            gray = cv2.equalizeHist(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
            min_side = max(20, int(min(w, h) * 0.025))
            for cascade, profile in self.cascades:
                for flipped in ((False, True) if profile else (False,)):
                    src = cv2.flip(gray, 1) if flipped else gray
                    found = cascade.detectMultiScale(src, scaleFactor=1.08, minNeighbors=4,
                                                     minSize=(min_side, min_side))
                    for (x, y, fw, fh) in found:
                        boxes.append((int(w - x - fw) if flipped else int(x), int(y), int(fw), int(fh)))
        return boxes


def find_faces(img: Image.Image, detector: "FaceFinder | None" = None) -> list[tuple[int, int, int, int]]:
    """얼굴 영역 (x, y, w, h) 목록."""
    return (detector or FaceFinder()).find(img)


def blur_faces(img: Image.Image, boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    img = img.copy()
    W, H = img.size
    for x, y, w, h in boxes:
        pad_w, pad_h = int(w * 0.35), int(h * 0.45)          # 머리카락·턱까지 넉넉하게
        box = (max(0, x - pad_w), max(0, y - pad_h), min(W, x + w + pad_w), min(H, y + h + pad_h))
        region = img.crop(box)
        small = region.resize((max(1, region.width // 12), max(1, region.height // 12)), Image.BILINEAR)
        region = small.resize(region.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(max(6, w // 8)))
        img.paste(region, box)
    return img


def _clean(path: Path) -> tuple[Image.Image, str]:
    """사진을 열어 회전(EXIF 방향)을 바로잡고, 촬영 시각만 읽은 뒤 EXIF가 없는 새 이미지로 돌려준다."""
    with Image.open(path) as src:
        taken = _taken_at(src)
        img = ImageOps.exif_transpose(src).convert("RGB")
    img.thumbnail((LONG_SIDE, LONG_SIDE), Image.LANCZOS)
    clean = Image.new("RGB", img.size)
    clean.paste(img)                                        # 픽셀만 옮겨 담아 원본 정보가 따라오지 않게 한다
    return clean, taken


def prepare(folder: Folder, out_dir: Path, detector: "FaceFinder | None" = None,
            models_dir: Path | None = None) -> list[dict]:
    """사진을 처리해 OUTPUT_DIR/photo_01.jpg …로 저장하고, 메모를 memo.txt로 복사한다.
    결과 목록은 photos.json에도 남긴다(글쓰기·검수가 읽는다). 원본 폴더는 건드리지 않는다.
    models_dir: 얼굴 찾기 모델(YuNet)을 받아 두는 곳(보통 data/models)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    detector = detector or FaceFinder(models_dir)
    has_heif = _register_heif()
    loaded = []
    for path in folder.photos:
        if path.suffix.lower() in (".heic", ".heif") and not has_heif:
            log.warning("HEIC 사진을 열 도구(pillow-heif)가 없어 뺍니다: %s", path.name)
            continue
        try:
            img, taken = _clean(path)
        except Exception as e:  # noqa: BLE001 - 깨진 사진 한 장 때문에 글을 멈추지 않는다
            log.warning("사진을 열지 못해 뺍니다(%s): %s", path.name, e)
            continue
        loaded.append((taken or "9999", path.name, path, img, taken))
    loaded.sort(key=lambda t: (t[0], t[1]))
    if len(loaded) < MIN_PHOTOS:
        raise PhotoError(f"'{folder.name}' 폴더에서 쓸 수 있는 사진이 {len(loaded)}장뿐입니다({MIN_PHOTOS}장 이상 필요)")

    photos = []
    for i, (_, name, path, img, taken) in enumerate(loaded[:MAX_PHOTOS], 1):
        faces = find_faces(img, detector)
        if faces:
            img = blur_faces(img, faces)
        key = f"photo_{i:02d}"
        img.save(out_dir / f"{key}.jpg", "JPEG", quality=88, optimize=True)   # exif를 넘기지 않음 → 위치 정보 없음
        photos.append({"name": key, "file": f"{key}.jpg", "original": name, "taken": taken,
                       "faces_blurred": len(faces), "width": img.width, "height": img.height})
        log.info("사진 준비 %s ← %s (얼굴 흐림 %d곳)", key, name, len(faces))
    if folder.memo:
        (out_dir / "memo.txt").write_text(read_memo(folder.memo), encoding="utf-8")
    (out_dir / "photos.json").write_text(json.dumps({"place_folder": folder.name, "photos": photos},
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    return photos


def archive(folder: Path, root: Path, today: str) -> Path:
    """발행이 끝난 폴더를 _발행됨/'날짜 폴더이름'으로 옮긴다(다시 쓰지 않게)."""
    done = root / DONE_DIR
    done.mkdir(parents=True, exist_ok=True)
    target = done / f"{today} {folder.name}"
    n = 2
    while target.exists():
        target = done / f"{today} {folder.name} ({n})"
        n += 1
    shutil.move(str(folder), str(target))
    return target
