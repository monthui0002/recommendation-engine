import os
import sys
from pathlib import Path


os.environ["MONGODB_URI"] = "mongodb://localhost:27017"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
