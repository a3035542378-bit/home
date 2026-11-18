"""Verify fixture credentials using synthetic audio and local provider responses."""
import base64
from unittest.mock import patch

from ergou import voice_policy
from tests.test_speech import recording


def preview_credential(db,user,group,**fields):
    version=voice_policy.settings(db,user,group)["version"]
    audio=recording()
    with (patch("ergou.speech.recognize",return_value="二狗二狗语音测试"),
          patch("ergou.speech.synthesize_wav",return_value=base64.b64decode(audio))):
        return voice_policy.test_credential(db,user,group,dict(version=version,audio=audio,**fields))


def verify_credential(db,user,group,**fields):
    version=voice_policy.settings(db,user,group)["version"]
    tested=preview_credential(db,user,group,**fields)
    return voice_policy.configure(db,user,group,dict(version=version,action="activate",ticket=tested["ticket"]))
