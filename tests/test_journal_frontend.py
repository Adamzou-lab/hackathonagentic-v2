"""Vérifications du journal de supervision (palier 4).

La logique d'affichage est écrite en JavaScript ; elle est vérifiée par Node,
sans navigateur, sans réseau et sans appel API. Le test est ignoré proprement
si Node est absent, plutôt que de faire échouer la suite pour un outil manquant.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / 'tests' / 'journal_checks.mjs'


@pytest.mark.skipif(shutil.which('node') is None, reason='Node absent de la machine')
def test_journal_de_supervision():
    resultat = subprocess.run(['node', str(SCRIPT)], cwd=str(RACINE),
                              capture_output=True, text=True, timeout=60)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    assert 'verifications passees' in resultat.stdout


def test_module_sans_dependance_reseau():
    """Le module d'affichage ne doit contenir ni appel réseau ni clé."""
    source = (RACINE / 'app' / 'static' / 'journal.js').read_text(encoding='utf-8')
    for interdit in ('fetch(', 'XMLHttpRequest', 'sk-ant', 'Authorization'):
        assert interdit not in source, f'{interdit} ne doit pas figurer dans journal.js'
