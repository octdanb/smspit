from app.otp import extract_code


def test_extracts_common_code_formats():
    assert extract_code("Your verification code is 482913") == "482913"
    assert extract_code("Use code 4829 to sign in") == "4829"
    assert extract_code("PIN: 48291382") == "48291382"


def test_ignores_out_of_range_digit_runs():
    assert extract_code("Call us on 021") is None  # too short
    assert extract_code("Ref 123456789") is None  # too long
    assert extract_code("Total $12.3456 charged") is None  # decimal fragment


def test_no_code():
    assert extract_code("Hello, how are you?") is None


def test_custom_regex_with_group():
    assert extract_code("token=ABC123", r"token=(\w+)") == "ABC123"


def test_custom_regex_without_group():
    assert extract_code("magic WORD99 here", r"WORD\d+") == "WORD99"
