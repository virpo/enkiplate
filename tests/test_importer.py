import json
import pytest
from enki_core.config import Config
from enki_core.importer import import_cards
from enki_core.store import Store


def test_personal_cards_extend_course_and_keep_history(tmp_path):
    store = Store(Config(tmp_path))
    path = tmp_path / "cards.json"
    row = {
        "id": "kyoto",
        "jp": "水をください。",
        "reading": "mizu o kudasai.",
        "meaning": "Water, please.",
    }
    path.write_text(json.dumps([row]))
    assert import_cards(store, path) == 1
    original = store.card("custom:kyoto")
    path.write_text(json.dumps([{**row, "meaning": "Some water, please."}]))
    import_cards(store, path)
    assert store.card("custom:kyoto")["pk"] == original["pk"]
    assert store.card("custom:kyoto")["meaning"] == "Some water, please."
    path.write_text(json.dumps([{**row, "jp": "あ" * 41}]))
    with pytest.raises(ValueError):
        import_cards(store, path)
