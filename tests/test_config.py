from mate.config import MateSettings, load_settings


def test_load_settings_creates_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("MATE_HOME", str(tmp_path / "mate-home"))
    settings = load_settings()
    assert isinstance(settings, MateSettings)
    for required in (settings.paths.base_dir, settings.paths.logs_dir, settings.paths.config_dir):
        assert required.exists()


def test_ui_defaults():
    settings = MateSettings()
    assert settings.ui.opacity == 0.5
    assert settings.ui.theme == "light"
