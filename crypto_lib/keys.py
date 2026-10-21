from typing import Tuple, Any, Dict
from . import generate_paillier_keypair, dl_generate_keypair, PaillierKeypair
import json
import os
from pathlib import Path
import tempfile

def _key_file() -> Path:
    configured = os.environ.get("PERSONAL_AGENT_KEY_FILE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "local_store" / "crypto_keys.json"


def _load_or_create_keys() -> dict:
    path = _key_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            if lock_file.read(1) == b"":
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as key_file:
                    return json.load(key_file)

            paillier = generate_paillier_keypair()
            tp_sk, tp_pk = dl_generate_keypair()
            ap_sk, ap_pk = dl_generate_keypair()
            keys = {
                "tp_paillier_public": paillier.public,
                "tp_paillier_private": paillier.private,
                "tp_dl_sk": tp_sk,
                "tp_dl_pk": tp_pk,
                "ap_sk": ap_sk,
                "ap_pk": ap_pk,
            }
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".crypto-keys-",
                suffix=".tmp",
                delete=False,
            ) as key_file:
                temp_path = Path(key_file.name)
                json.dump(keys, key_file)
                key_file.flush()
                os.fsync(key_file.fileno())
            os.replace(temp_path, path)
            return keys
        finally:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


_KEYS = _load_or_create_keys()
TP_PAILLIER = PaillierKeypair(
    public=_KEYS["tp_paillier_public"],
    private=_KEYS["tp_paillier_private"],
)
TP_DL_SK = int(_KEYS["tp_dl_sk"])
TP_DL_PK = int(_KEYS["tp_dl_pk"])
AP_SK = int(_KEYS["ap_sk"])
AP_PK = int(_KEYS["ap_pk"])
