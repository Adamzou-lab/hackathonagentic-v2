"""Une coupure de processus isolé, sans réseau, fournisseur IA ni serveur utilisateur."""
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "palier4_fault.py"


def run(tmp_path, child_code, *options, stdin=None):
    log = tmp_path / "fault.jsonl"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(log), *options, "--",
         sys.executable, "-c", child_code],
        input=stdin, text=True, capture_output=True, timeout=12,
    )
    events = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, events


def test_coupure_bornee_sans_redemarrage(tmp_path):
    result, events = run(tmp_path, "import time; time.sleep(60)", "--after", "0.1")
    assert result.returncode == 0, result.stderr
    assert [e["kind"] for e in events] == [
        "supervisor_started", "child_started", "fault_requested", "fault_applied",
    ]
    request, applied = events[-2:]
    assert applied["data"]["returncode"] == -signal.SIGKILL
    assert applied["data"]["child_pid"] == events[1]["data"]["child_pid"]
    assert applied["data"]["requested_at"] == request["at"]
    assert datetime.fromisoformat(request["at"]) <= datetime.fromisoformat(applied["data"]["applied_at"])
    assert applied["data"]["interrupted_at"] is None
    assert applied["data"]["observation"] == "child_exit_confirmed"
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert len({e["session_id"] for e in events}) == 1
    assert "Aucun redémarrage" in result.stdout


def test_operateur_declenche_la_coupure(tmp_path):
    result, events = run(tmp_path, "import time; time.sleep(60)", stdin="couper\n")
    assert result.returncode == 0, result.stderr
    assert events[-1]["kind"] == "fault_applied"


def test_sortie_naturelle_n_est_pas_une_coupure(tmp_path):
    result, events = run(tmp_path, "raise SystemExit(7)", "--after", "1")
    assert result.returncode == 3
    assert events[-1]["kind"] == "child_exited_before_fault"
    assert events[-1]["data"]["returncode"] == 7
    assert not any(e["kind"] == "fault_applied" for e in events)


def test_quitter_nettoie_son_enfant_sans_faux_succes(tmp_path):
    result, events = run(tmp_path, "import time; time.sleep(60)", stdin="quitter\n")
    assert result.returncode == 3, result.stderr
    assert "fault_cancelled" in [e["kind"] for e in events]
    assert events[-1]["kind"] == "cleanup_completed"
    assert not any(e["kind"] == "fault_applied" for e in events)


def test_commande_absente_et_preuve_existante_sont_refusees(tmp_path):
    log = tmp_path / "fault.jsonl"
    log.write_text("preuve précédente\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(log), "--after", "0", "--",
         sys.executable, "-c", "raise RuntimeError('ne doit pas tourner')"],
        text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == 74
    assert log.read_text() == "preuve précédente\n"
    missing = tmp_path / "missing.jsonl"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(missing), "--", "/missing/command"],
        text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == 70
    assert json.loads(missing.read_text().splitlines()[-1])["kind"] == "child_start_failed"


def test_demande_est_fsync_avant_le_signal(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("fault_checkpoint", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    real_fsync = module.os.fsync

    def fsync(fd):
        calls.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", fsync)

    class Child:
        pid = 123
        returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            calls.append("kill")

        def wait(self, timeout):
            self.returncode = -signal.SIGKILL

    audit = module.Audit(tmp_path / "ordered.jsonl")
    try:
        assert module.cut(Child(), audit) == 0
    finally:
        audit.close()
    assert calls == ["fsync", "kill", "fsync"]


def test_panne_du_journal_ne_laisse_pas_un_enfant_orphelin():
    spec = importlib.util.spec_from_file_location("fault_checkpoint", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class BrokenAudit:
        def emit(self, *args, **kwargs):
            raise OSError("disk unavailable")

    class Child:
        pid = 123
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -signal.SIGTERM

        def wait(self, timeout):
            return self.returncode

    child = Child()
    with pytest.raises(OSError):
        module.cleanup(child, BrokenAudit(), "test")
    assert child.returncode == -signal.SIGTERM
