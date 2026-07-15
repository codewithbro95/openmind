from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from openmind.core.config import ImageExtractionSettings
from openmind.core.models import ExtractedDocument
from openmind.extractors.base import Extractor
from openmind.extractors.ocr import OCRExtractionError, OCRUnavailableError, RapidOCRBackend


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class ImageDescriptionProvider(Protocol):
    model_name: str

    def describe(self, path: Path, prompt: str, max_new_tokens: int) -> str:
        ...


class ImageExtractor(Extractor):
    extensions = IMAGE_EXTENSIONS

    def __init__(
        self,
        settings: ImageExtractionSettings | None = None,
        description_provider: ImageDescriptionProvider | None = None,
        ocr_backend: RapidOCRBackend | None = None,
    ):
        self.settings = settings or ImageExtractionSettings()
        if description_provider is None:
            raise ValueError("ImageExtractor requires an image description provider.")
        self.description_provider = description_provider
        self.ocr_backend = ocr_backend or RapidOCRBackend()

    def extract(self, path: str) -> ExtractedDocument:
        file_path = Path(path)
        metadata = _image_metadata(file_path)
        metadata.update(
            {
                "extension": file_path.suffix.lower(),
                "file_type": "image",
                "raw_image_stored": False,
                "image_description_model": self.settings.model,
                "image_description_prompt": self.settings.prompt,
                "image_ocr_used": False,
            }
        )

        if not self.settings.enabled:
            metadata["image_description_error"] = "Image indexing is disabled in config."
            return ExtractedDocument(
                file_path=str(file_path),
                title=file_path.name,
                text="",
                metadata=metadata,
            )

        description = ""
        try:
            description = self.description_provider.describe(
                file_path,
                prompt=self.settings.prompt,
                max_new_tokens=self.settings.max_new_tokens,
            ).strip()
        except Exception as exc:
            metadata["image_description_error"] = str(exc)

        ocr_text = ""
        if self.settings.ocr_enabled:
            try:
                ocr_text = self.ocr_backend.extract_image_text(file_path).strip()
            except (OCRUnavailableError, OCRExtractionError) as exc:
                metadata["image_ocr_error"] = str(exc)

        if description:
            metadata["image_description"] = description
        if ocr_text:
            metadata["image_ocr_text"] = ocr_text
            metadata["image_ocr_used"] = True

        text = _combined_image_text(
            description=description,
            ocr_text=ocr_text,
            metadata=metadata,
        )
        return ExtractedDocument(
            file_path=str(file_path),
            title=file_path.name,
            text=text,
            metadata=metadata,
        )


def _image_metadata(path: Path) -> dict:
    metadata: dict[str, Any] = {
        "image_width": None,
        "image_height": None,
        "image_mode": None,
        "image_format": None,
        "image_file_size": path.stat().st_size if path.exists() else None,
    }
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        with Image.open(path) as image:
            metadata.update(
                {
                    "image_width": int(image.width),
                    "image_height": int(image.height),
                    "image_mode": image.mode,
                    "image_format": image.format,
                }
            )
            if image.info:
                metadata["image_info"] = _safe_metadata_mapping(image.info)
            exif = image.getexif()
            if exif:
                metadata["image_exif"] = {
                    str(TAGS.get(tag_id, tag_id)): _safe_metadata_value(value)
                    for tag_id, value in exif.items()
                }
    except Exception as exc:
        metadata["image_metadata_error"] = str(exc)
    return metadata


def _combined_image_text(description: str, ocr_text: str, metadata: dict[str, Any]) -> str:
    parts = []
    if description:
        parts.append(f"Image description:\n{description}")
    if ocr_text:
        parts.append(f"Visible text OCR:\n{ocr_text}")
    metadata_text = _searchable_metadata_text(metadata)
    if metadata_text:
        parts.append(f"Image metadata:\n{metadata_text}")
    return "\n\n".join(parts).strip()


def _safe_metadata_mapping(values: dict[Any, Any]) -> dict[str, Any]:
    return {
        str(key): sanitized
        for key, value in values.items()
        if (sanitized := _safe_metadata_value(value)) is not None
    }


def _safe_metadata_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes):
        return f"<binary {len(value)} bytes>"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple | list | set):
        return [
            sanitized
            for item in value
            if (sanitized := _safe_metadata_value(item)) is not None
        ]
    if isinstance(value, dict):
        return _safe_metadata_mapping(value)
    return str(value)


def _searchable_metadata_text(metadata: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in metadata.items():
        if key in {
            "image_description",
            "image_description_prompt",
            "image_ocr_text",
            "image_metadata_error",
        }:
            continue
        lines.extend(_metadata_lines(key, value))
    return "\n".join(lines)


def _metadata_lines(key: str, value: Any) -> list[str]:
    if value is None or value == "" or value == [] or value == {}:
        return []
    if isinstance(value, dict):
        lines: list[str] = []
        for inner_key, inner_value in value.items():
            lines.extend(_metadata_lines(f"{key}.{inner_key}", inner_value))
        return lines
    if isinstance(value, list):
        rendered = ", ".join(str(item) for item in value if item is not None and item != "")
        return [f"{key}: {rendered}"] if rendered else []
    return [f"{key}: {value}"]
