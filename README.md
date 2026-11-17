# cospend-ha

Home Assistant integration and Lovelace card for [Nextcloud Cospend](https://github.com/julien-nc/cospend-nc),
the shared budget manager. The goal is the same experience as the Android app
[Cowspent](https://github.com/helcel-net/cowspent), inside your dashboards and automations.

> **Status: under development (milestone M1).** Nothing is usable in Home Assistant yet: the
> repository contains the project skeleton, the CI, a throwaway test server and the Cospend client
> library (`aiocospend`). Do not install it in a
> production Home Assistant.

## Planned features

- **Integration** — choose which Cospend projects to connect; services to create, edit and delete
  expenses from automations; sensors (balances, last expense); events when expenses change.
- **Offline mode** — expenses created while Nextcloud is unreachable are queued and sent later,
  without duplicates.
- **Lovelace card** — the same screens as Cowspent: expenses, splits (even, custom, percent),
  currencies, search, statistics, settlement plan.
- **Scope** — Nextcloud Cospend servers only (Cospend ≥ 1.6.1). IHateMoney is not supported.

## Repository layout

| Path | Content |
| --- | --- |
| `custom_components/cospend/` | Home Assistant integration (domain `cospend`) |
| `lib/aiocospend/` | Async Python client for the Cospend OCS API (to be published on PyPI) |
| `src/cospend_card/` | Lovelace card (TypeScript + Lit), built into the integration at release time |
| `dev/` | Disposable Nextcloud + Cospend test server (Docker) |
| `tests/` | Integration tests and contract tests |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
pytest lib/aiocospend/tests      # client (n'a pas besoin de Home Assistant)
pytest tests/components          # intégration (Home Assistant)
ruff check . && ruff format --check .

cd src/cospend_card && npm ci && npm test && npm run build
```

Contract tests run against a real Nextcloud with Cospend:

```bash
docker compose -f dev/docker-compose.yml up -d
./dev/setup-nextcloud.sh          # waits for Nextcloud, installs Cospend
export COSPEND_TEST_URL=http://localhost:8080 COSPEND_TEST_USER=admin COSPEND_TEST_PASSWORD=admin-test-password
pytest -m contract
docker compose -f dev/docker-compose.yml down -v
```

The test server uses throwaway credentials and must never be exposed to a network.

## License and credits

GPL-3.0 — see [`LICENSE`](LICENSE) and [`NOTICE.md`](NOTICE.md).

---

## Français

Intégration Home Assistant et carte Lovelace pour [Nextcloud Cospend](https://github.com/julien-nc/cospend-nc),
avec les mêmes fonctionnalités que l'application Android [Cowspent](https://github.com/helcel-net/cowspent).

**État : en développement (jalon M0).** Le dépôt ne contient pour l'instant que le squelette du projet,
l'intégration continue, un serveur de test jetable et la bibliothèque client `aiocospend` ; ne l'installez pas sur un Home Assistant de production.

Prévu : choix des projets à connecter, services pour créer / modifier / supprimer des dépenses depuis
les automatisations, mode hors ligne (file d'attente sans doublons), carte Lovelace complète.
Fonctionne uniquement avec un serveur Nextcloud (Cospend ≥ 1.6.1) ; IHateMoney n'est pas pris en charge.
Voir la section « Development » ci-dessus pour les commandes de test.
