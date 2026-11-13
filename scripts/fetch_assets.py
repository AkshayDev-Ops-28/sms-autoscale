"""One-time download of the model (Hugging Face) and the dataset (UCI)."""
import io
import random
import urllib.request
import zipfile
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent.parent
UCI_ZIP = "https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip"

print("Downloading model ...")
snapshot_download(
    "omarash/sms-spam-distilbert",
    local_dir=ROOT / "models" / "sms-spam-distilbert",
    allow_patterns=["*.json", "*.safetensors", "*.txt"],
)

print("Downloading dataset ...")
raw = urllib.request.urlopen(UCI_ZIP, timeout=60).read()
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    text = z.read("SMSSpamCollection").decode("utf-8")
data = ROOT / "data"
data.mkdir(exist_ok=True)
(data / "SMSSpamCollection").write_text(text, encoding="utf-8")

# Small sample used as the request corpus for the load generator (fits in a ConfigMap)
msgs = [l.split("\t", 1)[1] for l in text.splitlines() if "\t" in l]
sample = random.Random(42).sample(msgs, 1000)
(data / "sms_sample.txt").write_text("\n".join(sample), encoding="utf-8")
print(f"Done: {len(msgs)} messages, sample of {len(sample)} written.")
