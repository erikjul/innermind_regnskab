"""Sikker opbevaring af originale bilag samt klargøring af billeder til aflæsning."""
import base64
import hashlib
import io
import mimetypes
import re
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

from . import config

MIME_BY_EXT = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif", ".heic": "image/heic", ".heif": "image/heif",
               ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp"}


def sikkert_filnavn(navn: str) -> str:
    navn = Path(navn or "bilag").name
    navn = re.sub(r"[^A-Za-z0-9æøåÆØÅ._-]+", "_", navn).strip("._") or "bilag"
    return navn[:120]


def gem_bilag(indhold: bytes, original_filnavn: str, bilagsnr: int) -> dict:
    """Gemmer det originale dokument uændret under data/bilag/<år>/ og returnerer metadata."""
    ext = Path(original_filnavn).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise ValueError(f"Filtypen {ext or '(ingen)'} understøttes ikke. Brug PDF, PNG, JPG, WEBP eller HEIC.")
    if len(indhold) == 0:
        raise ValueError("Filen er tom.")
    if len(indhold) > config.MAX_UPLOAD_BYTES:
        raise ValueError("Filen er for stor (maks. 32 MB).")
    sha = hashlib.sha256(indhold).hexdigest()
    mappe = config.BILAG_DIR / str(date.today().year)
    mappe.mkdir(parents=True, exist_ok=True)
    sti = mappe / f"{bilagsnr:06d}_{sikkert_filnavn(original_filnavn)}"
    sti.write_bytes(indhold)
    return {"fil_sti": str(sti.relative_to(config.DATA_DIR)), "sha256": sha, "stoerrelse": len(indhold),
            "mime": MIME_BY_EXT.get(ext) or mimetypes.guess_type(original_filnavn)[0] or "application/octet-stream"}


def laes_bilag(fil_sti: str) -> bytes:
    return (config.DATA_DIR / fil_sti).read_bytes()


def er_pdf(mime: str) -> bool:
    return mime == "application/pdf"


def normaliser_billede(indhold: bytes, maks_side: int = 2000) -> tuple[bytes, str]:
    """Klargør et kamerabillede/scanning: retter rotation fra EXIF, konverterer HEIC m.m. til JPEG,
    nedskalerer store billeder og forbedrer kontrast let. Returnerer (bytes, mime)."""
    img = Image.open(io.BytesIO(indhold))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((maks_side, maks_side))
    if img.mode == "RGB":
        img = ImageOps.autocontrast(img, cutoff=1)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue(), "image/jpeg"


def forhaandsvisning(indhold: bytes, mime: str, maks_side: int = 1200) -> tuple[bytes, str]:
    """Lille visning af et bilag til browseren (PDF'er vises direkte)."""
    if er_pdf(mime):
        return indhold, mime
    try:
        return normaliser_billede(indhold, maks_side)
    except Exception:
        return indhold, mime


def til_base64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("ascii")
