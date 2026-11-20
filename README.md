# cospend-ha

Home Assistant integration and Lovelace card for [Nextcloud Cospend](https://github.com/julien-nc/cospend-nc),
the shared budget manager. The goal is the same experience as the Android app
[Cowspent](https://github.com/helcel-net/cowspent), inside your dashboards and automations.

> **Status: under development (milestone M5).** The integration reads your projects (sensors,
> events), provides services to add, update and delete expenses, and queues them when Nextcloud is
> unreachable. The Lovelace card shows balances, expenses, search and details . Do not rely on it in a production Home Assistant.

## Planned features

- **Integration** — choose which Cospend projects to connect; services to create, edit and delete
  expenses from automations; sensors (balances, last expense); events when expenses change.
- **Offline mode** — expenses created while Nextcloud is unreachable are queued and sent later,
  without duplicates.
- **Lovelace card** — the same screens as Cowspent: expenses, splits (even, custom, percent),
  currencies, search, statistics, settlement plan.
- **Scope** — Nextcloud Cospend servers only (Cospend ≥ 1.6.1). IHateMoney is not supported.

## Connecting to Nextcloud

The setup asks how to reach your server:

- **Web address (http or https)** — your usual Nextcloud URL, with an optional sub-folder.
- **Local IP address and port** — for example `192.168.1.20` and `8080`, plus a "Use HTTPS"
  switch. No domain name or reverse proxy needed. Nextcloud only answers on an address listed in
  `trusted_domains`; if it refuses, add yours with
  `occ config:system:set trusted_domains 2 --value=192.168.1.20`.

Both choices are also offered when you reconfigure the connection, so you can switch an existing
entry from the domain name to the local IP (and back) without losing your projects. The account must
stay the same.

## Lovelace card

The integration serves its own card: nothing to add in the dashboard resources. Add a card
**Cospend** from the card picker (the visual editor lets you choose the project and the blocks),
or in YAML:

```yaml
type: custom:cospend-card
project: my-project        # optional: without it, a selector lists all the projects
title: Shared budget       # optional
show_balances: true        # member balances
show_bills: true           # expense list with details
show_search: true          # search field
allow_write: true          # add / delete expenses from the card
show_settlement: true      # "Settle up" button: who owes whom, with one-tap reimbursement
show_stats: true           # "Statistics" button: table, charts and flow diagram, with filters
allow_manage: false        # project settings (gear): true = every user, false = Home Assistant administrators only
page_size: 20              # expenses loaded at a time
```

The card follows your Home Assistant theme (light, dark, custom themes) and language (English and
French). It shows the balances, the expense list (custom splits are shown as one expense), a search
and the detail of each expense with everyone's share. It updates on its own and shows the
operations still waiting in the offline queue. You can add an expense (title, amount or calculation such as `12,5 + 7`, payer, participants,
date, category, payment mode, comment), split it evenly, by amounts or by percentages, enter it in
a foreign currency, make it repeat, edit it later and delete it after a confirmation (it goes to the
Nextcloud trash). Offline, the operation is queued like any service call. With maintainer access, a
gear button (Home Assistant administrators only, unless `allow_manage` is set) opens the project settings: members, categories, payment modes and currencies (these
changes need a connection to Nextcloud). The amount, participants
and currency of a custom-split expense cannot be edited: delete it and create it again. Set `allow_write: false`
for a read-only dashboard. The card is built when a release is published: a copy of the repository
without a release has the integration but no card.

## Services

| Service | What it does |
| --- | --- |
| `cospend.add_bill` | Add an expense. `amount` can be a calculation (`12,5 + 7`). `split_mode`: `even` (one bill), `amounts` or `percent` (one bill per participant, like Cowspent, with `shares`). Optional `currency` + `exchange_rate`, `category`, `payment_mode`, `date`, `comment`, `repeat`. |
| `cospend.update_bill` | Change some fields of a bill. The amount and participants of a custom-split bill cannot be changed (delete and recreate it). |
| `cospend.delete_bill` | Move a bill to the Cospend trash (the whole custom-split group by default). |
| `cospend.add_member` / `update_member` / `delete_member` | Manage the project's members (name, weight, color, active). A member who has bills is disabled by Cospend instead of deleted. |
| `cospend.add_category` / `update_category` / `delete_category` | Manage categories (name, emoji icon, `#rrggbb` color). |
| `cospend.add_payment_mode` / `update_payment_mode` / `delete_payment_mode` | Same for payment modes. |
| `cospend.add_currency` / `update_currency` / `delete_currency` | Manage secondary currencies and their exchange rate. |

The management services need **maintainer** access on the project and are **not queued** when
Nextcloud is unreachable: they fail instead, because replaying an addition or a deletion later could
create duplicates or hit another item.

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

**État : en développement (jalon M5).** L'intégration lit vos projets (capteurs, événements), fournit les services `cospend.add_bill`, `cospend.update_bill` et `cospend.delete_bill`, et met les écritures en file d'attente quand Nextcloud est injoignable (rejeu sans doublon, conflits signalés). 

Connexion : adresse web (http / https) **ou** adresse IP locale + port, au choix, à l'installation comme à la reconfiguration. Avec une IP, ajoutez-la aux `trusted_domains` de Nextcloud (`occ config:system:set trusted_domains 2 --value=192.168.1.20`).

Carte Lovelace (`custom:cospend-card`) : soldes, liste des dépenses (répartitions personnalisées regroupées), recherche et détail avec la part de chacun. Elle suit le thème de Home Assistant, se met à jour toute seule et s'ajoute depuis le sélecteur de cartes (éditeur visuel inclus). On peut y ajouter une dépense (répartition égale, par montants ou par pourcentages, devise étrangère, répétition), la modifier et la supprimer après confirmation (corbeille de Nextcloud) ; hors ligne, l'opération est mise en file d'attente. Avec le niveau gestionnaire, une roue crantée ouvre les réglages du projet : membres, catégories, modes de paiement et devises (ces modifications exigent une connexion à Nextcloud). Le montant, les participants et la devise d'une répartition personnalisée ne se modifient pas (supprimer puis recréer). Le bouton « Remboursements » (`show_settlement`) affiche le plan de Cospend (qui doit combien à qui, vos lignes en premier) et enregistre un remboursement en un geste : dépense payée par le débiteur au profit du créditeur, catégorie 💰 Remboursement ; si Nextcloud ne répond pas, le plan est calculé localement et l'enregistrement est mis en file d'attente. Le bouton « Statistiques » (`show_stats`) ouvre un tableau (par membre : payé, part et solde ; par catégorie, mode de paiement et mois), des graphiques (dépenses par mois empilées par catégorie, dépenses par catégorie) et un diagramme de Sankey (qui a payé, dans quelle catégorie, pour qui), avec des filtres : période, payé par, pour, catégorie, mode de paiement, remboursements. Les chiffres sont calculés par Home Assistant sur les dépenses déjà synchronisées : ils fonctionnent hors ligne et excluent par défaut les remboursements. `allow_write: false` rend la carte en lecture seule ; la roue crantée (réglages du projet) est réservée aux administrateurs de Home Assistant ; cocher `allow_manage` (éditeur visuel) l'ouvre à tous les utilisateurs. Le niveau gestionnaire sur Nextcloud reste exigé dans les deux cas. C'est un réglage d'affichage : les services `cospend.*` restent appelables par tout utilisateur autorisé à appeler des services.

Prévu : choix des projets à connecter, services pour créer / modifier / supprimer des dépenses depuis
les automatisations, mode hors ligne (file d'attente sans doublons), carte Lovelace complète.
Fonctionne uniquement avec un serveur Nextcloud (Cospend ≥ 1.6.1) ; IHateMoney n'est pas pris en charge.
Voir la section « Development » ci-dessus pour les commandes de test.
