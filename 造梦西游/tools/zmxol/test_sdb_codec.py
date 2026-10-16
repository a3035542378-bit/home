import base64
import json

import pytest
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes

from sdb_codec import TableDecodeError, decode_table


KEY = b"test-key"


def encrypt(plaintext: bytes) -> bytes:
    encoder = Cipher(TripleDES(KEY * 3), modes.ECB()).encryptor()
    return base64.b64encode(encoder.update(plaintext) + encoder.finalize())


def wrap(value) -> bytes:
    data = json.dumps(value, ensure_ascii=False).encode()
    padding = 8 - len(data) % 8
    return encrypt(data + bytes([padding]) * padding)


def test_decodes_a_table_with_chinese_and_base64_line_breaks():
    table = {"100001": {"name": "九重天", "sections": [110000, 110001]}}
    payload = wrap(table)
    payload = b"\r\n".join(payload[i:i + 24] for i in range(0, len(payload), 24))
    assert decode_table(payload, KEY) == table


@pytest.mark.parametrize("payload", [b"", b"not!base64", base64.b64encode(b"short")])
def test_rejects_malformed_ciphertext(payload):
    with pytest.raises(TableDecodeError):
        decode_table(payload, KEY)


def test_rejects_an_invalid_key_length():
    with pytest.raises(TableDecodeError, match="eight bytes"):
        decode_table(wrap({}), b"short")


def test_rejects_invalid_padding():
    with pytest.raises(TableDecodeError, match="padding"):
        decode_table(encrypt(b"{}      "), KEY)


def test_rejects_invalid_json():
    with pytest.raises(TableDecodeError, match="JSON"):
        decode_table(encrypt(b"broken\x02\x02"), KEY)


def test_rejects_non_object_json():
    with pytest.raises(TableDecodeError, match="object"):
        decode_table(wrap([1, 2]), KEY)
