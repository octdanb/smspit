from app.segments import apply_smart_encoding, segment_count


def test_short_gsm7_body_is_one_segment():
    assert segment_count("hello world") == ("gsm7", 1)


def test_gsm7_boundary_160():
    assert segment_count("a" * 160) == ("gsm7", 1)
    assert segment_count("a" * 161) == ("gsm7", 2)


def test_gsm7_concatenated_uses_153_per_segment():
    assert segment_count("a" * 306) == ("gsm7", 2)
    assert segment_count("a" * 307) == ("gsm7", 3)


def test_gsm7_extended_chars_count_double():
    # 80 euro signs = 160 septets = 1 segment; one more char overflows.
    assert segment_count("€" * 80) == ("gsm7", 1)
    assert segment_count("€" * 80 + "a") == ("gsm7", 2)


def test_unicode_falls_back_to_ucs2():
    assert segment_count("héllo 😀") == ("ucs2", 1)


def test_ucs2_boundary_70():
    assert segment_count("ก" * 70) == ("ucs2", 1)
    assert segment_count("ก" * 71) == ("ucs2", 2)


def test_ucs2_concatenated_uses_67_per_segment():
    assert segment_count("ก" * 134) == ("ucs2", 2)
    assert segment_count("ก" * 135) == ("ucs2", 3)


def test_astral_chars_take_two_utf16_units():
    assert segment_count("😀" * 35) == ("ucs2", 1)
    assert segment_count("😀" * 36) == ("ucs2", 2)


def test_empty_body_is_one_segment():
    assert segment_count("") == ("gsm7", 1)


def test_smart_encoding_maps_lookalikes_to_gsm7():
    assert apply_smart_encoding("“hi” — ok…") == '"hi" - ok...'
    # Without smart encoding the curly quotes force UCS-2.
    assert segment_count("“hi”")[0] == "ucs2"
    assert segment_count("“hi”", smart_encoded=True)[0] == "gsm7"
