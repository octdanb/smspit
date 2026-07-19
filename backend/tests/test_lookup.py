from tests.conftest import AUTH


def lookup(client, number, **params):
    return client.get(f"/v2/PhoneNumbers/{number}", params=params, auth=AUTH)


def test_valid_us_number(client):
    data = lookup(client, "+14155552671").json()
    assert data["valid"] is True
    assert data["phone_number"] == "+14155552671"
    assert data["calling_country_code"] == "1"
    assert data["country_code"] == "US"
    assert data["national_format"] == "(415) 555-2671"
    assert data["validation_errors"] == []
    assert data["line_type_intelligence"] is None  # not requested
    assert data["caller_name"] is None


def test_valid_nz_number(client):
    data = lookup(client, "+64211234567").json()
    assert data["valid"] is True
    assert data["country_code"] == "NZ"
    assert data["calling_country_code"] == "64"


def test_national_format_with_country_code_param(client):
    data = lookup(client, "021 123 4567", CountryCode="NZ").json()
    assert data["valid"] is True
    assert data["phone_number"] == "+64211234567"


def test_invalid_number(client):
    data = lookup(client, "+1415555").json()
    assert data["valid"] is False
    assert data["validation_errors"] == ["INVALID_LENGTH"]

    garbage = lookup(client, "not-a-number").json()
    assert garbage["valid"] is False
    assert garbage["validation_errors"]  # parse error surfaced


def test_line_type_intelligence_default_and_override(client):
    data = lookup(client, "+14155552671", Fields="line_type_intelligence").json()
    assert data["line_type_intelligence"]["type"] == "mobile"

    client.put(
        "/api/settings",
        json={"lookup_line_types": {"+14155552671": "nonFixedVoip"}},
    )
    data = lookup(client, "+14155552671", Fields="line_type_intelligence").json()
    assert data["line_type_intelligence"]["type"] == "nonFixedVoip"
