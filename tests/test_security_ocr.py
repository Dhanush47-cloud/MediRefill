import os
import pytest
from cryptography.fernet import Fernet
from secure_files import encrypt_bytes, decrypt_bytes, PrescriptionCryptoError
from prescription_ai import extract_prescription

def test_prescription_encryption_roundtrip(monkeypatch):
    monkeypatch.setenv('PRESCRIPTION_ENCRYPTION_KEY', Fernet.generate_key().decode())
    original=b'synthetic prescription content'
    encrypted=encrypt_bytes(original)
    assert encrypted != original
    assert decrypt_bytes(encrypted) == original

def test_encryption_refuses_missing_key(monkeypatch):
    monkeypatch.delenv('PRESCRIPTION_ENCRYPTION_KEY', raising=False)
    with pytest.raises(PrescriptionCryptoError):
        encrypt_bytes(b'synthetic')

def test_ocr_rejects_unsupported_extension():
    with pytest.raises(ValueError):
        extract_prescription(b'content', 'prescription.docx')

def test_ocr_rejects_empty_upload():
    with pytest.raises(ValueError):
        extract_prescription(b'', 'prescription.png')

def test_ocr_extracts_handwritten_style_candidate_as_unmatched_draft():
    from io import BytesIO
    from PIL import Image, ImageDraw
    image=Image.new('RGB',(900,250),'white')
    ImageDraw.Draw(image).text((30,80),'Metformin 500 mg',fill='black')
    stream=BytesIO(); image.save(stream,format='PNG')
    draft=extract_prescription(stream.getvalue(),'sample.png')
    assert draft.review_required is True
    assert draft.medicines
    assert draft.medicines[0]['match_status']=='unmatched_draft'
    assert 'Metformin' in draft.raw_text
