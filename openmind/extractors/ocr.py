from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class OCRUnavailableError(RuntimeError):
    pass


class OCRExtractionError(RuntimeError):
    pass


class RapidOCRBackend:
    name = "rapidocr-onnxruntime+pypdfium2"

    def __init__(self, scale: float = 2.0):
        self.scale = scale
        self._engine = None

    def extract_pdf_text(self, path: Path, language: str = "eng", timeout: int = 600) -> str:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise OCRUnavailableError(
                "OCR fallback requires Python OCR dependencies. Run "
                '`uv pip install -e ".[dev]"` from the OpenMind project.'
            ) from exc

        document = pdfium.PdfDocument(str(path))
        pages: list[str] = []
        try:
            for page_index in range(len(document)):
                page = document[page_index]
                bitmap = page.render(scale=self.scale)
                image = bitmap.to_pil()
                with tempfile.NamedTemporaryFile(suffix=".png") as temp_image:
                    image.save(temp_image.name)
                    rows, _elapsed = self._rapidocr()(temp_image.name)
                page.close()
                if rows:
                    lines = [_ocr_row_text(row) for row in rows]
                    text = "\n".join(line for line in lines if line).strip()
                    if text:
                        pages.append(f"\n\n[Page {page_index + 1}]\n{text}")
        finally:
            document.close()

        return "\n".join(pages).strip()

    def extract_image_text(self, path: Path) -> str:
        rows, _elapsed = self._rapidocr()(str(path))
        if not rows:
            return ""
        lines = [_ocr_row_text(row) for row in rows]
        return "\n".join(line for line in lines if line).strip()

    def _rapidocr(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise OCRUnavailableError(
                "OCR requires rapidocr-onnxruntime. Reinstall OpenMind with the published "
                "package or run `uv pip install -e .` from the project."
            ) from exc

        if self._engine is None:
            self._engine = RapidOCR()
        return self._engine


class OCRmyPDFBackend:
    name = "ocrmypdf+tesseract"

    def extract_pdf_text(self, path: Path, language: str = "eng", timeout: int = 600) -> str:
        executable = shutil.which("ocrmypdf")
        if executable is None:
            raise OCRUnavailableError(
                "OCR fallback requires OCRmyPDF, Tesseract, and Ghostscript. "
                "Install them locally, then run indexing again. On macOS: "
                "`brew install ocrmypdf tesseract ghostscript`."
            )

        with tempfile.TemporaryDirectory(prefix="openmind-ocr-") as tmpdir:
            temp_dir = Path(tmpdir)
            output_pdf = temp_dir / "ocr-output.pdf"
            sidecar_txt = temp_dir / "ocr-output.txt"
            command = [
                executable,
                "--force-ocr",
                "--language",
                language,
                "--sidecar",
                str(sidecar_txt),
                str(path),
                str(output_pdf),
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise OCRExtractionError(
                    f"OCR timed out after {timeout} seconds for {path.name}."
                ) from exc

            if result.returncode != 0:
                message = (result.stderr or result.stdout or "").strip()
                raise OCRExtractionError(
                    f"OCRmyPDF failed for {path.name}: {message or 'unknown OCR error'}"
                )

            if sidecar_txt.exists():
                return sidecar_txt.read_text(encoding="utf-8", errors="replace").strip()

            raise OCRExtractionError(f"OCRmyPDF did not produce sidecar text for {path.name}.")


def _ocr_row_text(row) -> str:
    if not isinstance(row, (list, tuple)) or len(row) < 2:
        return ""
    value = row[1]
    return "" if value is None else str(value).strip()
