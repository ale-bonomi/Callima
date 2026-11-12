import pytest
from pydantic import ValidationError

from crate.config import Config, load_config, save_config


def test_roundtrip(tmp_path):
    p = save_config(Config(), tmp_path / "c.yaml")
    assert load_config(p).max_depth == 3


def test_rejects_bad_values():
    with pytest.raises(ValidationError):
        Config(review_threshold=2)
    with pytest.raises(ValidationError):
        Config(duplicates="shred")
