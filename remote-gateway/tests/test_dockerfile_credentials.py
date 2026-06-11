"""Guard the Dockerfile credential-decoding contract.

The CMD must prefer GOOGLE_ADC_JSON (authorized_user ADC from the per-client
internal OAuth app) and fall back to the legacy GOOGLE_SA_JSON name so
already-deployed instances keep working. ADC autodetects the JSON type, so
both credential kinds work through the same file.
"""
from pathlib import Path

DOCKERFILE = Path(__file__).parent.parent.parent / "Dockerfile"


def test_cmd_prefers_adc_json_with_sa_fallback():
    assert "${GOOGLE_ADC_JSON:-$GOOGLE_SA_JSON}" in DOCKERFILE.read_text()


def test_cmd_exports_application_credentials_path():
    assert "GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-adc.json" in DOCKERFILE.read_text()
