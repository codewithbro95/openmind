from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from openmind.providers.lmstudio.client import LMStudioClient


class LMStudioImageDescriptionProvider:
    def __init__(self, client: LMStudioClient, model: str):
        self.client = client
        self.model_name = model

    def describe(self, path: Path, prompt: str, max_new_tokens: int) -> str:
        self.client.load_model_if_needed(self.model_name)
        result = self.client.chat(
            self.model_name,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_data_url(path)},
                        },
                    ],
                }
            ],
            max_tokens=max_new_tokens,
        )
        return result.content.strip()


def _image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
