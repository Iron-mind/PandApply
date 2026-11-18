import pytest
from pydantic import ValidationError

from pandapply.configuration import (
    Configuration,
    load_config,
    patch_settings,
    read_settings,
    save_config,
)
from pandapply.storage import connect, migrate


def test_config_roundtrip_and_defaults(tmp_path):
    path = tmp_path / "config.json"
    config = load_config(path)
    assert config.dry_run and not config.auto_apply_enabled
    save_config(path, config)
    assert load_config(path) == config


def test_config_rejects_unknown_and_invalid_values():
    with pytest.raises(ValidationError):
        Configuration.model_validate({"min_match_score": 1.2})
    with pytest.raises(ValidationError):
        Configuration.model_validate({"auto_apply_enabled": "true"})
    with pytest.raises(ValidationError):
        Configuration.model_validate({"unknown": 1})


def test_settings_revisions_are_transactional_and_preserve_legacy(tmp_path):
    database = tmp_path / "data.db"
    legacy = tmp_path / "config.json"
    migrate(database)
    save_config(legacy, Configuration(locale="es-CO"))
    with connect(database) as db:
        assert read_settings(db, legacy).locale == "es-CO"
        settings = patch_settings(db, legacy, {"min_match_score": 0.9}, actor="cli")
        assert settings.locale == "es-CO" and settings.min_match_score == 0.9
        patch_settings(db, legacy, {"min_match_score": 0.9}, actor="cli")
        assert db.execute("SELECT count(*) FROM config_revisions").fetchone()[0] == 1
        with pytest.raises(ValidationError):
            patch_settings(db, legacy, {"min_match_score": 4.0}, actor="web")
        assert read_settings(db, legacy).min_match_score == 0.9
        assert db.execute("SELECT count(*) FROM config_revisions").fetchone()[0] == 1
