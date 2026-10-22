"""Persist explicit retry-file ownership; never discover files for deletion by glob."""
import json
import os
import stat


COMPANION_SUFFIXES = (".edl", ".nfo")


def manifest(download):
    raw = getattr(download, "retained_captures_json", None)
    if not isinstance(raw, str) or not raw:
        return {"attempts": [], "selected": None}
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("attempts"), list):
        raise ValueError("Invalid retained-capture ownership record")
    return value


def save(download, value):
    download.retained_captures_json = json.dumps(value) if value["attempts"] else None


def identity(path):
    if not path:
        return None
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            return None
        return {"path": os.path.realpath(path), "dev": info.st_dev,
                "ino": info.st_ino, "size": info.st_size, "mtime_ns": info.st_mtime_ns}
    except OSError:
        return None


def unchanged(receipt):
    return isinstance(receipt, dict) and identity(receipt.get("path")) == receipt


def remember(download, receipt=None):
    """Called only for the current owned capture, before a new attempt starts."""
    value = manifest(download)
    receipt = receipt or identity(download.output_path)
    if receipt is None:
        return
    if not any(item.get("media") == receipt for item in value["attempts"]):
        value["attempts"].append({
            "media": receipt,
            # Deferred raw attempts have not produced companions. Never infer
            # ownership of an older sidecar merely from a matching filename.
            "companions": [],
            "raw_duration_seconds": download.raw_duration_seconds,
            "duration_analysis_status": download.duration_analysis_status,
            "duration_analysis_reason": download.duration_analysis_reason,
            "interruption_reason": download.interruption_reason,
            "short_file_failed": bool(download.short_file_failed),
        })
    save(download, value)


def select_input(download):
    value = manifest(download)
    if value["attempts"]:
        value["selected"] = identity(download.output_path)
        save(download, value)


def cleanup(value, protected_paths, keep_selected):
    """Delete only unchanged explicitly owned files. Return unresolved entries."""
    protected = {os.path.realpath(path) for path in protected_paths if path}
    protected_inodes = set()
    for path in protected:
        entry = identity(path)
        if entry:
            protected_inodes.add((entry["dev"], entry["ino"]))
    if keep_selected and isinstance(value.get("selected"), dict):
        selected = value["selected"]
        protected.add(selected["path"])
        protected_inodes.add((selected["dev"], selected["ino"]))
    remaining, errors = [], []
    for attempt in value["attempts"]:
        pending = []
        for receipt in [attempt.get("media"), *attempt.get("companions", [])]:
            if not isinstance(receipt, dict) or not isinstance(receipt.get("path"), str):
                errors.append("Invalid retained-file receipt; cleanup skipped")
                pending.append(receipt)
                continue
            path = receipt["path"]
            if path in protected or (receipt.get("dev"), receipt.get("ino")) in protected_inodes:
                continue
            if not os.path.lexists(path):
                continue
            if not unchanged(receipt):
                errors.append("A retained file changed; it was not deleted")
                pending.append(receipt)
                continue
            try:
                os.unlink(path)
            except OSError as exc:
                errors.append(f"Retained-file cleanup failed: {exc.strerror or type(exc).__name__}")
                pending.append(receipt)
        if pending:
            remaining.append({**attempt, "media": pending[0], "companions": pending[1:]})
    return {**value, "attempts": remaining}, errors
