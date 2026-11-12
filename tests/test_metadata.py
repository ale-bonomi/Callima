import pytest

from crate.analyze.metadata import parse, parse_key


@pytest.mark.parametrize(
    ("stem", "folders", "type_", "loop"),
    [
        ("KICK_01", (), "kick", None),
        ("CY_SNARE_Tight_03", ("Snares",), "snare", None),
        ("BMW_Kicks_One Shot_Punchy", ("Kicks",), "kick", False),
        ("Lofi Drum Loop 90 BPM", ("Drum Loops",), "drum", True),
        ("sample_12", ("Cymatics Pack", "Hi Hats"), "hat", None),
        ("Vox_Chop_120_Fmin", ("Vocals",), "vocal", None),
        ("808_Glide_F#", ("808s",), "808", None),
    ],
)
def test_type_and_loop(stem, folders, type_, loop):
    m = parse(stem, folders)
    assert m.type == type_
    assert m.loop is loop


def test_unknown_goes_to_zero_confidence():
    assert parse("asdf_001", ("Pack",)).type is None


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Pad_Cmin", "Cmin"),
        ("Keys_F#m_120", "F#min"),
        ("Loop_A_maj", "Amaj"),
        ("Chords Bb minor", "Bbmin"),
        ("Emotional_Pad", None),
        ("Bass_Am", "Amin"),
    ],
)
def test_keys(text, key):
    assert parse_key(text) == key


def test_bpm_explicit_and_bare():
    assert parse("Melody Loop 128bpm Am", ()).bpm == 128
    assert parse("Drum_Loop_95_Dry", ()).bpm == 95
    assert parse("Kick_100", ()).bpm is None  # bare numbers only count for loops


def test_filename_beats_folder_but_lowers_confidence():
    m = parse("Snare_01", ("Kicks",))
    assert m.type == "snare" and m.confidence < 0.9
