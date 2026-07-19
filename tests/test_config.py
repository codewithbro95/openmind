from openmind.core.config import (
    ExtractionSettings,
    ImageExtractionSettings,
    IndexingSettings,
    ModelSettings,
    OCRSettings,
    OpenMindConfig,
    ProviderSettings,
)


def test_config_save_and_load_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    config = OpenMindConfig(
        provider=ProviderSettings(
            name="lmstudio",
            base_url="http://localhost:1234",
            api_token_env="LM_API_TOKEN",
        ),
        models=ModelSettings(chat_model="chat-key", embedding_model="embed-key"),
        indexing=IndexingSettings(auto_start_after_setup=True, background=True),
        extraction=ExtractionSettings(
            ocr=OCRSettings(
                enabled=True,
                backend="ocrmypdf",
                min_text_chars_per_page=120,
            ),
            images=ImageExtractionSettings(
                enabled=True,
                model="vision-key",
                prompt="Describe this image.",
                ocr_enabled=False,
                max_new_tokens=123,
            ),
        ),
    )

    config.save(path)
    loaded = OpenMindConfig.load(path)

    assert loaded.provider.name == "lmstudio"
    assert loaded.models.chat_model == "chat-key"
    assert loaded.models.embedding_model == "embed-key"
    assert loaded.indexing.background is True
    assert loaded.extraction.ocr.enabled is True
    assert loaded.extraction.ocr.backend == "ocrmypdf"
    assert loaded.extraction.ocr.min_text_chars_per_page == 120
    assert loaded.extraction.images.enabled is True
    assert loaded.extraction.images.model == "vision-key"
    assert loaded.extraction.images.prompt == "Describe this image."
    assert loaded.extraction.images.ocr_enabled is False
    assert loaded.extraction.images.max_new_tokens == 123
    assert list(tmp_path.glob(".config.toml.*.tmp")) == []


def test_default_config_uses_python_installed_ocr_backend():
    config = OpenMindConfig()

    assert config.extraction.ocr.enabled is True
    assert config.extraction.ocr.backend == "rapidocr"
    assert config.extraction.images.enabled is True
    assert config.extraction.images.model == "ggml-org/SmolVLM-500M-Instruct-GGUF"
