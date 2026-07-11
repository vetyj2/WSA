from __future__ import annotations

from typing import Any, Dict, List

from .hermes_command_catalog_1 import default_commands_chunk_1
from .hermes_command_catalog_2 import default_commands_chunk_2


def _default_commands() -> List[Dict[str, Any]]:
    return [
        *default_commands_chunk_1(),
        *default_commands_chunk_2(),
    ]
