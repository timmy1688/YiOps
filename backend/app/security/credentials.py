import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class CredentialVault:
    """Small local encrypted store adapter for the single-node MVP."""

    def __init__(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[3] / ".runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        key_path = runtime_dir / "credential.key"
        if not key_path.exists():
            descriptor, candidate_name = tempfile.mkstemp(
                prefix=".credential.", suffix=".tmp", dir=runtime_dir
            )
            candidate_path = Path(candidate_name)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as key_file:
                    key_file.write(Fernet.generate_key())
                try:
                    os.link(candidate_path, key_path)
                except FileExistsError:
                    pass
            finally:
                candidate_path.unlink(missing_ok=True)
        self._fernet = Fernet(key_path.read_bytes().strip())

    def encrypt(self, value: dict[str, str]) -> str:
        payload = json.dumps(value, ensure_ascii=False).encode()
        return f"enc:v1:{self._fernet.encrypt(payload).decode()}"

    def decrypt(self, value: str | None) -> dict[str, str]:
        if not value:
            return {}
        if not value.startswith("enc:v1:"):
            return {"token": value}
        try:
            payload = self._fernet.decrypt(value.removeprefix("enc:v1:").encode())
            parsed = json.loads(payload)
            return {str(key): str(item) for key, item in parsed.items() if item}
        except (InvalidToken, json.JSONDecodeError):
            return {}
