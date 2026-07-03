from openmind.core.config import (
    IndexingSettings,
    ModelSettings,
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
    )

    config.save(path)
    loaded = OpenMindConfig.load(path)

    assert loaded.provider.name == "lmstudio"
    assert loaded.models.chat_model == "chat-key"
    assert loaded.models.embedding_model == "embed-key"
    assert loaded.indexing.background is True
