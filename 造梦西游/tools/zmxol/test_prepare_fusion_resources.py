from io import BytesIO
import zipfile

import pytest

from prepare_fusion_resources import SOURCE_PREFIX, collect_resources


def archive_bytes(change=None):
    entries = {}
    for pet_id in (221, 229, 9001, 9003):
        entries.update({f"{pet_id}.json": b'{"skeleton":{"spine":"2.1"}}',
                        f"{pet_id}.atlas": f"{pet_id}.png\nformat: RGBA8888\n".encode(),
                        f"{pet_id}.png": b"original texture fixture"})
    if change:
        change(entries)
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in entries.items():
            archive.writestr(SOURCE_PREFIX + name, raw)
    output.seek(0)
    return output, entries


def test_original_model_bytes_and_complete_pages_are_preserved():
    data, original = archive_bytes()
    with zipfile.ZipFile(data) as archive:
        entries = collect_resources(archive)
    assert len(entries) == 12
    assert entries == {"skeleton/pet/" + name: raw for name, raw in original.items()}


@pytest.mark.parametrize("case", ["missing", "unsafe", "empty"])
def test_reject_incomplete_or_unsafe_models(case):
    def change(entries):
        if case == "missing":
            del entries["9001.png"]
        elif case == "unsafe":
            entries["9001.atlas"] = b"../9001.png\nformat: RGBA8888\n"
        else:
            entries["9001.json"] = b""
    data, _ = archive_bytes(change)
    with zipfile.ZipFile(data) as archive, pytest.raises(ValueError):
        collect_resources(archive)
