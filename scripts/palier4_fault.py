#!/usr/bin/env python3
"""Coupure contrôlée d'un enfant de recette, avec preuve externe durable.

Ce superviseur ne connaît aucun PID fourni par l'utilisateur, ne redémarre pas
son enfant et n'appelle aucune API. Il n'est pas l'évaluation de dix scénarios.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import uuid


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Audit:
    """Un nouveau fichier par recette : aucune preuve existante n'est écrasée."""

    def __init__(self, path):
        self.handle = open(path, "x", encoding="utf-8")
        self.session_id = uuid.uuid4().hex
        self.seq = 0

    def emit(self, kind, **data):
        self.seq += 1
        event = {
            "schema_version": 1,
            "source": "external_fault_supervisor",
            "session_id": self.session_id,
            "seq": self.seq,
            "at": utc_now(),
            "monotonic_ns": time.monotonic_ns(),
            "kind": kind,
            "data": data,
        }
        self.handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        print(f"[{event['at']}] {kind} {json.dumps(data, ensure_ascii=False)}", flush=True)
        return event

    def close(self):
        self.handle.close()


def cleanup(child, audit, reason):
    """Ne pas laisser un enfant orphelin quand l'opérateur quitte la recette."""
    if child.poll() is not None:
        return
    audit_error = None

    def record(kind, **data):
        nonlocal audit_error
        try:
            audit.emit(kind, **data)
        except OSError as exc:
            # Une panne du témoin externe ne doit pas laisser l'enfant tourner.
            audit_error = exc

    record("cleanup_requested", child_pid=child.pid, reason=reason, signal="SIGTERM")
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        record("cleanup_forced", child_pid=child.pid, signal="SIGKILL")
        child.kill()
        child.wait(timeout=5)
    record("cleanup_completed", child_pid=child.pid, returncode=child.returncode)
    if audit_error:
        raise audit_error


def cut(child, audit):
    if child.poll() is not None:
        audit.emit("fault_not_applied", child_pid=child.pid,
                   reason="child_already_exited", returncode=child.returncode)
        return 4
    requested = audit.emit("fault_requested", child_pid=child.pid,
                           fault="process_kill", signal="SIGKILL")
    # emit() a fait flush + fsync : la demande est durable AVANT le signal.
    try:
        child.kill()
        child.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        audit.emit("fault_failed", child_pid=child.pid,
                   requested_at=requested["at"], code=type(exc).__name__)
        return 4
    if child.returncode != -signal.SIGKILL:
        # Une sortie naturelle concurrente n'est pas une coupure prouvée.
        audit.emit("fault_not_applied", child_pid=child.pid,
                   requested_at=requested["at"], reason="exit_without_sigkill",
                   returncode=child.returncode)
        return 4
    applied_at = utc_now()
    audit.emit(
        "fault_applied", child_pid=child.pid, fault="process_kill",
        requested_at=requested["at"], applied_at=applied_at,
        returncode=child.returncode, observation="child_exit_confirmed",
        interrupted_at=None,
        elapsed_ms=round((time.monotonic_ns() - requested["monotonic_ns"]) / 1_000_000, 3),
    )
    print("Coupure confirmée entre requested_at et applied_at. Aucun redémarrage.", flush=True)
    return 0


def supervise(command, audit, after=None):
    audit.emit("supervisor_started", executable=Path(command[0]).name,
               automatic_cut_after_seconds=after, restart_policy="never")
    try:
        # Ni shell ni PID libre. L'entrée opérateur n'est pas transmise à l'enfant.
        # Ne pas utiliser de lanceur qui crée un autre serveur (--reload, workers).
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        audit.emit("child_start_failed", code=type(exc).__name__)
        return 70
    try:
        audit.emit("child_started", child_pid=child.pid)
        deadline = time.monotonic() + after if after is not None else None
        if deadline is None:
            print("Attendez que le serveur soit prêt, lancez une mission, puis tapez couper et Entrée. "
                  "Tapez quitter pour arrêter la recette proprement.", flush=True)
        while True:
            if child.poll() is not None:
                audit.emit("child_exited_before_fault", child_pid=child.pid,
                           returncode=child.returncode)
                return 3
            if deadline is not None:
                if time.monotonic() >= deadline:
                    return cut(child, audit)
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                continue
            if not select.select([sys.stdin], [], [], 0.1)[0]:
                continue
            line = sys.stdin.readline()
            if line == "" or line.strip().lower() == "quitter":
                audit.emit("fault_cancelled", reason="input_closed" if line == "" else "operator_cancelled")
                return 3
            if line.strip().lower() == "couper":
                return cut(child, audit)
            print("Commande attendue : couper ou quitter.", flush=True)
    except KeyboardInterrupt:
        audit.emit("fault_cancelled", reason="operator_interrupt")
        return 3
    finally:
        cleanup(child, audit, "supervisor_finished")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True,
                        help="Nouveau fichier JSONL externe (ne doit pas exister).")
    parser.add_argument("--after", type=float,
                        help="Déclencher la coupure après ce délai, sinon attendre « couper ».")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="Commande enfant explicite après --, sans shell ni --reload.")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("une commande enfant est requise après --")
    if args.after is not None and (not 0 <= args.after <= 86400):
        parser.error("--after doit être compris entre 0 et 86400 secondes")
    if os.name != "posix":
        parser.error("cette recette SIGKILL nécessite macOS ou Linux")
    try:
        audit = Audit(args.log)
    except OSError as exc:
        print(f"Journal externe indisponible ({type(exc).__name__}) : aucun enfant lancé.", file=sys.stderr)
        return 74
    exit_code = 74
    try:
        exit_code = supervise(command, audit, args.after)
    except OSError as exc:
        print(f"Échec du journal externe ({type(exc).__name__}). La coupure n'est pas validée.", file=sys.stderr)
    finally:
        try:
            audit.close()
        except OSError as exc:
            print(f"Fermeture du journal échouée ({type(exc).__name__}). La coupure n'est pas validée.", file=sys.stderr)
            exit_code = 74
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
