# aiocospend

Client asynchrone (aiohttp) pour l'API OCS de [Nextcloud Cospend](https://github.com/julien-nc/cospend-nc).
Fait partie du dépôt [cospend-ha](https://github.com/SpaRtzZii/cospend-ha). Version 0.2.0.

```python
import time

import aiohttp
from aiocospend import CospendClient

async with aiohttp.ClientSession() as session:
    client = CospendClient(
        session, "https://cloud.exemple.org", "utilisateur", "mot-de-passe-d-application"
    )
    await client.check_connection()  # adresse, identifiants, version de Cospend (>= 1.6.1)

    project = (await client.get_projects())[0]  # membres, catégories, soldes inclus
    page = await client.get_bills(project.id)  # page.timestamp = curseur du prochain last_changed
    delta = await client.get_bills(project.id, last_changed=page.timestamp)

    bill_id = await client.create_bill(
        project.id,
        what="Courses",
        amount=42.5,
        payer_id=project.members[0].id,
        payed_for=[m.id for m in project.members],
        timestamp=int(time.time()),
        date=time.strftime("%Y-%m-%d"),
    )
    await client.update_bill(project.id, bill_id, amount=45)  # modification partielle
    await client.delete_bill(project.id, bill_id)  # corbeille
```

## Synchronisation incrémentale

```python
from aiocospend import ProjectBills

store = ProjectBills(project.id)
changes = await store.sync(
    client, full_sync_max_age=24 * 3600
)  # complète au besoin, sinon incrémentale
for bill in changes.added:
    ...  # changes.updated, changes.deleted ; changes.is_initial = première lecture
```

## À savoir (relevé sur Cospend 4.3.0)

- Les écritures sont envoyées en formulaire, avec tous les champs à la création (comme Cowspent).
- **Supprimer une dépense déjà en corbeille la supprime définitivement.** Le client ne rejoue jamais
  une suppression : relisez l'état de la dépense avant de réessayer.
- La lecture incrémentale (`last_changed`) ne renvoie pas les dépenses mises en corbeille ; on les
  repère par leur absence de `all_bill_ids`.
- Les montants renvoyés par le serveur (statistiques, remboursements) ne sont pas arrondis.

## Tests

```bash
pip install -e ".[test]"
pytest tests            # faux serveur Cospend local, sans réseau externe
```

## Publication sur PyPI (mainteneur)

Le paquet est publié par le workflow manuel `publish-aiocospend.yml`, sans mot de passe, par
« Trusted Publisher » : sur pypi.org, ajouter un *pending publisher* (propriétaire `SpaRtzZii`,
dépôt `cospend-ha`, workflow `publish-aiocospend.yml`, environnement `pypi`), créer l'environnement
`pypi` dans les réglages du dépôt GitHub, puis lancer le workflow depuis l'onglet Actions.
