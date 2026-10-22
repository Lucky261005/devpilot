from inventory.store import load_items


def test_load_items_missing_file_returns_empty(tmp_path):
    assert load_items(tmp_path / "missing.json") == []
