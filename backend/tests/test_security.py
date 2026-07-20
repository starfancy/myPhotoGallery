import time
import pytest
from myphoto.security import (
    TokenError,
    decode_token,
    hash_password,
    make_token,
    verify_password,
)


SECRET = "test-secret-32bytes-minimum-length-abcdef"


def test_hash_is_not_plain():
    h = hash_password("hunter2hunter2")
    assert "hunter2" not in h


def test_verify_success():
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter2hunter2", h) is True


def test_verify_failure():
    h = hash_password("hunter2hunter2")
    assert verify_password("wrong", h) is False


def test_hash_differs_between_calls():
    assert hash_password("same") != hash_password("same")


def test_token_roundtrip():
    token = make_token(SECRET, user_id=42, role="admin", ttl_seconds=3600)
    payload = decode_token(SECRET, token)
    assert payload["sub"] == 42
    assert payload["role"] == "admin"
    assert payload["exp"] > int(time.time())


def test_token_bad_signature():
    token = make_token(SECRET, 1, "viewer", 3600)
    with pytest.raises(TokenError):
        decode_token(SECRET + "x", token)


def test_token_expired():
    token = make_token(SECRET, 1, "viewer", ttl_seconds=-1)
    with pytest.raises(TokenError):
        decode_token(SECRET, token)


def test_token_malformed():
    with pytest.raises(TokenError):
        decode_token(SECRET, "not-a-jwt")
