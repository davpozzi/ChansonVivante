"""Composizione dei servizi applicativi usati dalla finestra."""
from .audio_processor import AudioProcessingMixin
from .model_manager import ModelManagerMixin
from .ui_bridge import UIQueueMixin


class DemucsBackend(ModelManagerMixin, AudioProcessingMixin, UIQueueMixin):
    """Unisce gestione modelli, pipeline audio e comunicazione con la UI."""

    pass
