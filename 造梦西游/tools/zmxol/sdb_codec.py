"""解析客户端的 DES/ECB 配置表；密钥仅由调用方在内存中提供。"""

import base64
import binascii
import json

from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes


class TableDecodeError(ValueError):
    """配置表不符合当前已验证的编码格式。"""


def decode_table(payload: bytes, key: bytes) -> dict:
    if len(key) != 8:
        raise TableDecodeError("DES key must contain eight bytes")
    try:
        ciphertext = base64.b64decode(b"".join(payload.split()), validate=True)
    except binascii.Error as error:
        raise TableDecodeError("Invalid Base64 table") from error
    if not ciphertext or len(ciphertext) % 8:
        raise TableDecodeError("Invalid DES block length")
    decoder = Cipher(TripleDES(key * 3), modes.ECB()).decryptor()
    plaintext = decoder.update(ciphertext) + decoder.finalize()
    padding = plaintext[-1]
    if not 1 <= padding <= 8 or plaintext[-padding:] != bytes([padding]) * padding:
        raise TableDecodeError("Invalid PKCS padding")
    try:
        table = json.loads(plaintext[:-padding])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TableDecodeError("Invalid JSON table") from error
    if not isinstance(table, dict):
        raise TableDecodeError("Expected a JSON object table")
    return table
