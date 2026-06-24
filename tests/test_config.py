"""Config module loads without error."""

from __future__ import annotations


def test_config_has_expected_keys():
    import config

    assert hasattr(config, "LLM_MODEL")
    assert hasattr(config, "EMBED_MODEL")
    assert hasattr(config, "VISION_MODEL")
    assert hasattr(config, "setup_logging")


def test_setup_logging_runs():
    import config

    config.setup_logging()
