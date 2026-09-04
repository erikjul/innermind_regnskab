import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("REGNSKAB_DATA_DIR", BASE_DIR / "data"))
BILAG_DIR = DATA_DIR / "bilag"
# Sæt REGNSKAB_BACKUP_DIR til en mappe, der synkroniseres til en cloud-tjeneste (OneDrive, Dropbox, Google Drive)
BACKUP_DIR = Path(os.environ.get("REGNSKAB_BACKUP_DIR", DATA_DIR / "backup"))
DB_PATH = DATA_DIR / "regnskab.db"
DATABASE_URL = os.environ.get("REGNSKAB_DATABASE_URL", f"sqlite:///{DB_PATH}")

# Model til fakturaaflæsning (Claude API)
CLAUDE_MODEL = os.environ.get("REGNSKAB_CLAUDE_MODEL", "claude-opus-5")

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".gif", ".tif", ".tiff", ".bmp"}
IMAGE_EXTENSIONS = ALLOWED_EXTENSIONS - {".pdf"}

# Bogføringslovens § 12: bilag og registreringer opbevares 5 år fra udgangen af regnskabsåret
OPBEVARINGSAAR = 5
