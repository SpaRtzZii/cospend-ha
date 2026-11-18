# cospend-ha

Home Assistant integration and Lovelace card for [Nextcloud Cospend](https://github.com/julien-nc/cospend-nc),
the shared budget manager. The goal is the same experience as the Android app
[Cowspent](https://github.com/helcel-net/cowspent), inside your dashboards and automations.

> **Status: under development (milestone M4).** The integration reads your projects (sensors,
> events), provides services to add, update and delete expenses, and queues them when Nextcloud is
> unreachable. The Lovelace card is not available yet. Do not rely on it in a production Home Assistant.

## Planned features

- **Integration** — choose which Cospend projects to connect; services to create, edit and delete
  expenses from automations; sensors (balances, last expense); events when expenses change.
- **Offline mode** — expenses created while Nextcloud is unreachable are queued and sent later,
  without duplicates.
- **Lovelace card** — the same screens as Cowspent: expenses, splits (even, custom, percent),
  currencies, search, statistics, settlement plan.
- **Scope** — Nextcloud Cospend servers only (Cospend ≥ 1.6.1). IHateMoney is not supported.

## Services

| Service | What it does |
| --- | --- |
| `cospend.add_bill` | Add an expense. `amount` can be a calculation (`12,5 + 7`). `split_mode`: `even` (one bill), `amounts` or `percent` (one bill per participant, like Cowspent, with `shares`). Optional `currency` + `exchange_rate`, `category`, `payment_mode`, `date`, `comment`, `repeat`. |
| `cospend.update_bill` | Change some fields of a bill. The amount and participants of a custom-split bill cannot be changed (delete and recreate it). |
| `cospend.delete_bill` | Move a bill to the Cospend trash (the whole custom-split group by default). |

Members, categories and payment modes can be given by name or identifier. Each service returns
the identifiers of the affected bills. A multi-bill operation that fails halfway is never retried
or rolled back: the error lists what was already done.

```yaml
action: cospend.add_bill
data:
  project: vacances
  title: Courses
  amount: "12,5 + 7"
  payer: Alice
  split_mode: percent
  owers: [Alice, Bob]
  shares: { Alice: 60, Bob: 40 }
response_variable: result
```

## Offline mode

If Cospend cannot be reached (network, maintenance, 5xx), `add_bill`, `update_bill` and
`delete_bill` queue the operation instead of failing: the response contains `queued: true` and an
`operation_id`. The queue is stored on disk, replayed every minute and at startup, in order, and
never creates duplicates or deletes twice. If a bill was changed or deleted elsewhere in the
meantime, the operation is **blocked** (a repair issue and a `cospend_operation_blocked` event tell
you) until you call `cospend.retry_queued` (`force: true` applies it anyway) or
`cospend.discard_queued`. A *Pending operations* sensor shows the queue of each project.
Invalid input, missing permissions and authentication errors are reported immediately, never queued.

Limitation: Home Assistant must have read the projects once to accept operations, so the
integration cannot start while Nextcloud is down (queued operations are kept and replayed later).

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
pytest tests/contract -m contract
docker compose -f dev/docker-compose.yml down -v
```

The test server uses throwaway credentials and must never be exposed to a network.

## License and credits

GPL-3.0 — see [`LICENSE`](LICENSE) and [`NOTICE.md`](NOTICE.md).

---

## Français

Intégration Home Assistant et carte Lovelace pour [Nextcloud Cospend](https://github.com/julien-nc/cospend-nc),
avec les mêmes fonctionnalités que l'application Android [Cowspent](https://github.com/helcel-net/cowspent).

**État : en développement (jalon M4).** L'intégration lit vos projets (capteurs, événements), fournit les services `cospend.add_bill`, `cospend.update_bill` et `cospend.delete_bill`, et met les écritures en file d'attente quand Nextcloud est injoignable (rejeu sans doublon, conflits signalés). La carte Lovelace n'est pas encore disponible.

Prévu : choix des projets à connecter, services pour créer / modifier / supprimer des dépenses depuis
les automatisations, mode hors ligne (file d'attente sans doublons), carte Lovelace complète.
Fonctionne uniquement avec un serveur Nextcloud (Cospend ≥ 1.6.1) ; IHateMoney n'est pas pris en charge.
Voir la section « Development » ci-dessus pour les commandes de test.
