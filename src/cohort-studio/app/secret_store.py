import json
import base64
import os
import re
import tempfile
import threading
import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


Provider = Literal["anthropic", "openai", "gemini", "openrouter", "openweight", "jev"]
_PROVIDERS = {"anthropic", "openai", "gemini", "openrouter", "openweight", "jev"}
_MCP_KEY = re.compile(r"^mcp:[A-Za-z0-9_-]{1,64}$")
_KEY_ARN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):kms:([a-z0-9-]+):[0-9]{12}:key/[0-9a-f-]{36}$")
_STORE_LOCK = threading.RLock()


@contextmanager
def _store_lock():
    with _STORE_LOCK:
        directory = _secure_directory()
        descriptor = os.open(directory / ".lock",
                             os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


class SecretStoreError(RuntimeError):
    pass


class SecretStoreSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    secret_id: str = Field(min_length=1, max_length=512)
    kms_key_arn: str = Field(min_length=1, max_length=256)
    region: str = Field(min_length=1, max_length=32)

    @classmethod
    def from_env(cls):
        secret_id = os.environ.get("STUDIO_LLM_SECRET_ID")
        kms_key_arn = os.environ.get("STUDIO_LLM_KMS_KEY_ID")
        if not secret_id and not kms_key_arn:
            return None
        if not secret_id or not kms_key_arn:
            raise SecretStoreError(
                "Secure model-key storage needs STUDIO_LLM_SECRET_ID and "
                "STUDIO_LLM_KMS_KEY_ID.")
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        if not region:
            raise SecretStoreError(
                "Secure model-key storage needs AWS_REGION or AWS_DEFAULT_REGION.")
        try:
            settings = cls(secret_id=secret_id, kms_key_arn=kms_key_arn,
                           region=region)
            match = _KEY_ARN.fullmatch(settings.kms_key_arn)
            if not match or match.group(2) != settings.region:
                raise ValueError()
            return settings
        except (ValidationError, ValueError):
            raise SecretStoreError(
                "Secure model-key storage settings are invalid; use a secret ID "
                "and a KMS key ARN in the configured AWS region.") from None


class StoredSecret(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    keys: dict[str, str] = Field(default_factory=dict, max_length=128)

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, keys: dict[str, str]) -> dict[str, str]:
        if any((key not in _PROVIDERS and not _MCP_KEY.fullmatch(key))
               or not value or len(value) > 8192
               for key, value in keys.items()):
            raise ValueError("Model key values are invalid.")
        return keys


def is_configured() -> bool:
    try:
        return SecretStoreSettings.from_env() is not None
    except SecretStoreError:
        return False


def has_backend_configuration() -> bool:
    return bool(os.environ.get("STUDIO_LLM_SECRET_ID")
                or os.environ.get("STUDIO_LLM_KMS_KEY_ID"))


def _client(settings: SecretStoreSettings):
    try:
        import boto3
        from botocore.config import Config

        return boto3.client("secretsmanager", region_name=settings.region,
                            config=Config(connect_timeout=3, read_timeout=5,
                                          retries={"max_attempts": 1,
                                                   "mode": "standard"}))
    except Exception:
        raise SecretStoreError("The secure model-key store is unavailable.") from None


def _code(error: Exception) -> str | None:
    return getattr(error, "response", {}).get("Error", {}).get("Code")


def _secret(settings: SecretStoreSettings, client) -> dict:
    try:
        response = client.get_secret_value(SecretId=settings.secret_id)
    except Exception as exc:
        if _code(exc) == "ResourceNotFoundException":
            return {"version": 1, "keys": {}}
        raise SecretStoreError(
            "The secure model-key store could not be read. Check the app role "
            "and Secrets Manager access.") from None
    raw = response.get("SecretString")
    try:
        stored = StoredSecret.model_validate_json(raw)
    except (ValidationError, TypeError):
        raise SecretStoreError(
            "The secure model-key secret has an invalid format.") from None
    return {"version": 1,
            "keys": {provider: key for provider, key in stored.keys.items()}}


def read_keys() -> dict[str, str]:
    with _store_lock():
        local, deleted = _read_local_state()
        try:
            settings = SecretStoreSettings.from_env()
            if settings is None:
                return local
            client = _client(settings)
            remote = _read_kms(settings, client)
        except SecretStoreError:
            return local
        merged = {**remote, **local}
        for key_name in deleted:
            merged.pop(key_name, None)
        if (local or deleted) and merged != remote:
            try:
                _write_kms(settings, merged)
            except SecretStoreError:
                return merged
            _delete_local_keys()
        elif local or deleted:
            _delete_local_keys()
        return merged


def write_keys(keys: dict[str, str]) -> None:
    try:
        normalized = StoredSecret.model_validate({"version": 1, "keys": keys})
    except ValidationError:
        raise SecretStoreError("The model-key update is invalid.") from None
    payload = json.dumps({"version": 1, "keys": normalized.keys})
    if len(payload.encode("utf-8")) > 60_000:
        raise SecretStoreError("The secure model-key store is full.")
    with _store_lock():
        local, deleted = _read_local_state()
        remote = {}
        try:
            settings = SecretStoreSettings.from_env()
            if settings is None:
                raise SecretStoreError("Secure model-key storage is not configured.")
            remote = _read_kms(settings, _client(settings))
            merged = {**remote, **local, **normalized.keys}
            merged_deleted = deleted - set(normalized.keys)
            for key_name in merged_deleted:
                merged.pop(key_name, None)
            _write_kms(settings, merged)
            _delete_local_keys()
        except SecretStoreError:
            merged = {**remote, **local, **normalized.keys}
            merged_deleted = deleted - set(normalized.keys)
            for key_name in merged_deleted:
                merged.pop(key_name, None)
            _write_local_keys(merged, merged_deleted)


def remove_key(key_name: str) -> None:
    with _store_lock():
        local, deleted = _read_local_state()
        try:
            settings = SecretStoreSettings.from_env()
        except SecretStoreError:
            settings = None
        if (settings is None and not has_backend_configuration()
                and not _local_paths()[0].exists()):
            return
        remote = {}
        try:
            if settings is not None:
                remote = _read_kms(settings, _client(settings))
                merged = {**remote, **local}
                for removed_key in deleted:
                    merged.pop(removed_key, None)
                merged.pop(key_name, None)
                _write_kms(settings, merged)
                _delete_local_keys()
                return
        except SecretStoreError:
            pass
        merged = {**remote, **local}
        merged.pop(key_name, None)
        deleted.add(key_name)
        _write_local_keys(merged, deleted)


def _write_kms(settings: SecretStoreSettings, keys: dict[str, str]) -> None:
    payload = json.dumps({"version": 1, "keys": keys})
    if len(payload.encode("utf-8")) > 60_000:
        raise SecretStoreError("The secure model-key store is full.")
    client = _client(settings)
    try:
        description = client.describe_secret(SecretId=settings.secret_id)
    except Exception as exc:
        if _code(exc) != "ResourceNotFoundException":
            raise SecretStoreError(
                "The secure model-key store could not be checked. Check the app "
                "role and Secrets Manager access.") from None
        try:
            client.create_secret(Name=settings.secret_id, SecretString=payload,
                                 KmsKeyId=settings.kms_key_arn)
            _confirm_write(settings, client, keys)
            return
        except Exception as create_error:
            if _code(create_error) != "ResourceExistsException":
                raise SecretStoreError(
                    "The secure model-key store could not be created. Check the "
                    "app role, KMS key policy, and Secrets Manager access.") from None
            try:
                description = client.describe_secret(SecretId=settings.secret_id)
            except Exception:
                raise SecretStoreError(
                    "The secure model-key store could not be checked after a "
                    "concurrent create.") from None
    if description.get("KmsKeyId") != settings.kms_key_arn:
        raise SecretStoreError(
            "The configured model-key secret uses a different KMS key. "
            "The app did not change it.")
    try:
        client.put_secret_value(SecretId=settings.secret_id,
                                SecretString=payload)
    except Exception:
        raise SecretStoreError(
            "The secure model-key store could not be updated. Check the app "
            "role, KMS key policy, and Secrets Manager access.") from None
    _confirm_write(settings, client, keys)


def _read_kms(settings: SecretStoreSettings, client) -> dict[str, str]:
    try:
        description = client.describe_secret(SecretId=settings.secret_id)
    except Exception as exc:
        if _code(exc) == "ResourceNotFoundException":
            return _secret(settings, client)["keys"]
        raise SecretStoreError("The secure model-key store could not be checked.") from None
    if description.get("KmsKeyId") != settings.kms_key_arn:
        raise SecretStoreError("The configured model-key secret uses a different KMS key.")
    return _secret(settings, client)["keys"]


def _confirm_write(settings: SecretStoreSettings, client,
                   expected: dict[str, str]) -> None:
    saved = _secret(settings, client)["keys"]
    if saved != expected:
        raise SecretStoreError(
            "The secure model-key write could not be confirmed.")


def _local_directory() -> Path:
    configured = os.environ.get("STUDIO_LOCAL_SECRET_DIR")
    if configured:
        return Path(configured)
    config_path = Path(os.environ.get(
        "STUDIO_CONFIG", str(Path(__file__).parent / "studio_config.json")))
    return config_path.parent / ".studio-secrets"


def _local_paths() -> tuple[Path, Path]:
    directory = _local_directory()
    return directory / "keys.enc", directory / "key"


def _secure_directory() -> Path:
    directory = _local_directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def _read_local_state() -> tuple[dict[str, str], set[str]]:
    data_path, key_path = _local_paths()
    if not data_path.exists():
        return {}, set()
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        os.chmod(data_path.parent, 0o700)
        os.chmod(data_path, 0o600)
        os.chmod(key_path, 0o600)
        key = key_path.read_bytes()
        if len(key) != 32:
            raise ValueError()
        envelope = json.loads(data_path.read_text())
        if envelope.get("version") != 1:
            raise ValueError()
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, b"cohort-studio-keys-v1")
        state = json.loads(plaintext)
        stored = StoredSecret.model_validate({
            "version": state.get("version"), "keys": state.get("keys")})
        removed = state.get("deleted", [])
        if not isinstance(removed, list) or any(
                not isinstance(key_name, str) or
                (key_name not in _PROVIDERS and not _MCP_KEY.fullmatch(key_name))
                for key_name in removed):
            raise ValueError()
        return stored.keys, set(removed)
    except Exception:
        raise SecretStoreError(
            "The encrypted local model-key store could not be read or verified.") from None


def _read_local_keys() -> dict[str, str]:
    return _read_local_state()[0]


def _atomic_private_write(path: Path, content: bytes) -> None:
    directory = _secure_directory()
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".keys-", dir=directory)
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        os.chmod(path, 0o600)
    except Exception:
        raise SecretStoreError(
            "The encrypted local model-key store could not be written.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_local_keys(keys: dict[str, str], deleted: set[str] | None = None) -> None:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        _secure_directory()
        data_path, key_path = _local_paths()
        previous, previous_deleted = _read_local_state()
        removed = (previous_deleted | (set(previous) - set(keys)))
        removed |= deleted or set()
        removed -= set(keys)
        if key_path.exists():
            key = key_path.read_bytes()
            if len(key) != 32:
                raise ValueError()
        else:
            key = os.urandom(32)
            _atomic_private_write(key_path, key)
        nonce = os.urandom(12)
        plaintext = json.dumps({"version": 1, "keys": keys,
                                "deleted": sorted(removed)}).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, b"cohort-studio-keys-v1")
        envelope = json.dumps({"version": 1,
                               "nonce": base64.b64encode(nonce).decode("ascii"),
                               "ciphertext": base64.b64encode(ciphertext).decode("ascii")})
        _atomic_private_write(data_path, envelope.encode("utf-8"))
    except SecretStoreError:
        raise
    except Exception:
        raise SecretStoreError(
            "The encrypted local model-key store could not be written.") from None


def _delete_local_keys() -> None:
    data_path, key_path = _local_paths()
    try:
        data_path.unlink(missing_ok=True)
        key_path.unlink(missing_ok=True)
    except OSError:
        raise SecretStoreError(
            "The encrypted local model-key copy could not be removed.") from None


def key_source(key_name: str) -> str | None:
    with _store_lock():
        local, deleted = _read_local_state()
        if key_name in deleted:
            return None
        if key_name in local:
            return "local_encrypted"
        try:
            settings = SecretStoreSettings.from_env()
            if settings is not None and key_name in _read_kms(settings, _client(settings)):
                return "secret_manager"
        except SecretStoreError:
            pass
        return None


def is_available() -> bool:
    with _store_lock():
        try:
            if _local_paths()[0].exists():
                _read_local_state()
                return True
            settings = SecretStoreSettings.from_env()
            if settings is None:
                return False
            _read_kms(settings, _client(settings))
            return True
        except SecretStoreError:
            return False
