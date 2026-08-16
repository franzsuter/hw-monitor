import sys
from unittest.mock import MagicMock

# Mock bs4 and playwright before importing scraper
sys.modules["bs4"] = MagicMock()
sys.modules["playwright"] = MagicMock()
sys.modules["playwright.async_api"] = MagicMock()

import json
import pytest
import os
from scraper import load_json, save_json

def test_load_json_file_exists(tmp_path):
    """Test loading JSON from an existing file."""
    d = tmp_path / "test.json"
    data = {"key": "value", "number": 123}
    d.write_text(json.dumps(data), encoding="utf-8")

    result = load_json(str(d), {})
    assert result == data

def test_load_json_file_not_exists(tmp_path):
    """Test loading JSON from a non-existent file returns default value."""
    filepath = tmp_path / "non_existent.json"
    default_val = {"status": "default"}

    result = load_json(str(filepath), default_val)
    assert result == default_val

def test_load_json_invalid_json(tmp_path):
    """Test loading from a file with invalid JSON raises JSONDecodeError."""
    d = tmp_path / "invalid.json"
    d.write_text("not a json string", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_json(str(d), {})

def test_save_json(tmp_path):
    """Test saving data to a JSON file."""
    d = tmp_path / "output.json"
    data = {"name": "Hagelregister", "active": True}

    save_json(str(d), data)

    assert os.path.exists(str(d))
    with open(str(d), 'r', encoding='utf-8') as f:
        saved_data = json.load(f)
    assert saved_data == data

def test_save_json_formatting(tmp_path):
    """Test that save_json uses correct formatting (indent=4, ensure_ascii=False)."""
    d = tmp_path / "format.json"
    data = {"umlaut": "äöü", "list": [1, 2]}

    save_json(str(d), data)

    content = d.read_text(encoding="utf-8")
    # Verify indentation (4 spaces)
    assert "    \"umlaut\"" in content
    # Verify ensure_ascii=False (characters are not escaped)
    assert "äöü" in content
    assert "\\u00e4" not in content
