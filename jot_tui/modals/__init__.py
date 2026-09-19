"""Textual modal factories grouped by feature."""

from .notes import build_note_modals
from .palette import build_command_palette_modal
from .progress import build_progress_modal
from .resources import build_common_modals
from .timelog import build_time_modals

__all__ = [
    "build_command_palette_modal",
    "build_common_modals",
    "build_note_modals",
    "build_progress_modal",
    "build_time_modals",
]
