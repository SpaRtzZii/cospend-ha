# Contribuer

1. Ouvrez une *issue* avant un changement important.
2. Installez l'environnement : `python -m venv .venv`, puis `pip install -r requirements-test.txt`.
3. Lancez les tests : `pytest lib/aiocospend/tests`, `pytest tests/components` et `ruff check .`.
4. Carte : `cd src/cospend_card && npm ci && npm test && npm run build`.
5. Tests de contrat contre un vrai serveur : voir la section « Développement » du `README.md`.

Toute reprise de code issu de Cowspent doit être signalée (voir `NOTICE.md`).
