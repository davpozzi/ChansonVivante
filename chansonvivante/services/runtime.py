import contextlib
import gc
import inspect
import os
import queue
import sys
import threading

# Limita il numero di thread delle librerie numeriche prima di importare PyTorch.
# Evita che BLAS/OpenMP saturino CPU e memoria su PC Windows con molti core.
for _thread_var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_thread_var] = "4"
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
from pathlib import Path
from urllib.parse import urlparse

# Tutti i dati scaricati durante l'esecuzione devono restare dentro ChansonVivante.
# In particolare, PyTorch/Demucs usa TORCH_HOME per i checkpoint dei modelli.
APP_ROOT = (
    Path(sys.executable).parent.resolve()
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)
APP_MODELS_DIR = APP_ROOT / "models"
APP_CACHE_DIR = APP_ROOT / ".cache"
APP_MODELS_DIR.mkdir(parents=True, exist_ok=True)
APP_CACHE_DIR.mkdir(parents=True, exist_ok=True)

os.environ["TORCH_HOME"] = str(APP_MODELS_DIR)
os.environ["HF_HOME"] = str(APP_MODELS_DIR / "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = str(APP_MODELS_DIR / "huggingface" / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(APP_MODELS_DIR / "huggingface" / "transformers")
os.environ["XDG_CACHE_HOME"] = str(APP_CACHE_DIR)

import yaml
import asyncio
import flet as ft


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value
    def set(self, value):
        self.value = value


torch = None
demucs = None
sf = None

GB = 1024 ** 3
VRAM_RESERVE_GB = 0.75
# Retry progressivamente più leggeri. None lascia a Demucs il segmento predefinito.
SEGMENT_RETRY_ORDER = [None, 5.0, 3.0, 2.0, 1.5]


def resource_path(relative_path):
    """Restituisce un percorso valido sia da sorgente sia da EXE."""
    return str((APP_ROOT / relative_path).resolve())


def is_cuda_oom(error):
    """Riconosce solo errori di memoria CUDA, senza nascondere altri bug."""
    oom_type = getattr(torch.cuda, "OutOfMemoryError", ())
    if oom_type and isinstance(error, oom_type):
        return True
    message = str(error).lower()
    return "out of memory" in message and ("cuda" in message or "cublas" in message)


def segment_for_budget(budget_gb):
    """Stima iniziale prudente; il budget è un obiettivo, non un hard cap."""
    if budget_gb >= 7.5:
        return None
    if budget_gb >= 5.0:
        return 5.0
    if budget_gb >= 3.2:
        return 3.0
    if budget_gb >= 2.0:
        return 2.0
    return 1.5


def available_cuda_memory():
    """Ritorna (memoria libera, totale) in GiB, oppure None se CUDA non è pronta."""
    try:
        if not torch.cuda.is_available():
            return None
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        return free_bytes / GB, total_bytes / GB
    except Exception:
        return None



class QueueLogStream:
    """Inoltra stdout/stderr al thread GUI senza bloccare l'elaborazione."""
    def __init__(self, log_queue, level):
        self.log_queue = log_queue
        self.level = level
        self.buffer = ""

    def write(self, text):
        if not text:
            return 0
        self.buffer += str(text)
        # tqdm usa \r per aggiornare la stessa riga; trattiamo anche \n.
        while "\n" in self.buffer or "\r" in self.buffer:
            positions = [p for p in (self.buffer.find("\n"), self.buffer.find("\r")) if p >= 0]
            pos = min(positions)
            line = self.buffer[:pos].strip()
            self.buffer = self.buffer[pos + 1:]
            if line:
                self.log_queue.put(("log", self.level, line))
        return len(text)

    def flush(self):
        line = self.buffer.strip()
        if line:
            self.log_queue.put(("log", self.level, line))
        self.buffer = ""

    def isatty(self):
        return False




