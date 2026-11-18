# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage [SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté (jalon M4)
- Mode hors ligne pour les écritures. Si Cospend est injoignable (réseau, maintenance, erreur 5xx),
  `add_bill`, `update_bill` et `delete_bill` mettent l'opération en file d'attente persistante
  (conservée au redémarrage) et répondent `queued: true` avec un `operation_id`. La file est
  rejouée toutes les minutes et au démarrage, dans l'ordre, par projet : rien ne passe devant une
  opération plus ancienne.
- Jamais de doublon ni de suppression rejouée à l'aveugle : une création dont la réponse s'est
  perdue est retrouvée sur le serveur (titre, seconde, payeur, montant, participants, commentaire)
  avant d'être recréée ; une modification déjà appliquée est ignorée ; une dépense déjà absente
  n'est pas supprimée une seconde fois ; une répartition personnalisée reprend à la part où elle
  s'était arrêtée.
- Les conflits ne sont jamais résolus en silence : si la dépense a été modifiée ou supprimée ailleurs
  entre-temps, l'opération est **bloquée**, une réparation (Repairs) est créée, et
  l'événement `cospend_operation_blocked` est émis. Les services `cospend.retry_queued`
  (avec `force: true` pour appliquer quand même) et `cospend.discard_queued` la résolvent.
- Capteur « Opérations en attente » par projet (nombre, détail en attributs) ; événements
  `cospend_operation_queued`, `cospend_operation_synced` et `cospend_operation_blocked`.
- Les erreurs de saisie, de droits ou d'authentification ne sont jamais mises en file : elles sont
  signalées tout de suite.
- aiocospend 0.4.0 : `plan_*` / `execute_*` (plans d'écriture sérialisables), `spec_matches_bill`,
  `fields_applied`, `is_transient`.

### Limite connue du mode hors ligne
- Si Home Assistant démarre alors que Cospend est injoignable, l'intégration ne peut pas se
  charger (la structure des projets est inconnue) : les services ne sont disponibles qu'après une
  première lecture réussie. Les opérations déjà en file sont conservées et rejouées ensuite.

### Ajouté
- Jalon M3 : services `cospend.add_bill`, `cospend.update_bill` et `cospend.delete_bill`
  (réponse : identifiants des dépenses concernées). Montant saisi comme nombre ou comme calcul
  (`12,5 + 7`) ; répartition égale, par montants ou par pourcentages (une dépense par
  participant, comme Cowspent, sans jamais perdre un centime) ; devise étrangère avec taux de
  change (métadonnée `#NOM:MONTANT@TAUX` dans le commentaire, au format exact de Cowspent, omise si le taux vaut 1) ; récurrence ; membres,
  catégories et modes de paiement désignés par leur nom ou leur identifiant.
- Regroupement strict des dépenses à répartition personnalisée : modifier ou supprimer l'une
  d'elles agit sur tout le groupe (suppression d'une seule part possible avec `whole_group: false`).
- Une opération multiple qui échoue en cours de route n'est jamais rejouée ni annulée : l'erreur
  indique les dépenses déjà traitées. Les suppressions vont toujours à la corbeille de Cospend.
- aiocospend 0.3.0 : `parse_amount`, `compute_split`, `group_bills`, `add_bill`, `update_bill`,
  `delete_bill`, résolution des noms, métadonnée de devise.
- Images de marque originales pour HACS et Home Assistant (`brand/`).

### Modifié
- Le faux client des tests d'intégration expose maintenant l'API d'écriture ; ses anciens
  assistants de scénario s'appellent `simulate_add`, `simulate_update` et `simulate_delete`.
- Dépendance : `aiocospend==0.4.0` (à publier sur PyPI avant la release).

### Corrigé
- La fiche de l'appareil affiche le nom du projet au lieu de « Project » à la fin de la configuration.

### Ajouté (jalons précédents)
- Jalon M2 : intégration Home Assistant en lecture. Configuration par l'interface (adresse, mot de
  passe d'application, choix des projets), nouvelle authentification, reconfiguration, options
  (projets, intervalle d'actualisation, resynchronisation complète) ; mise à jour périodique
  incrémentale ; un appareil par projet avec capteurs (nombre de dépenses, total, dépensé ce mois-ci,
  dernière dépense, solde / payé / dépensé de chaque membre, total par catégorie et par mode de
  paiement) ; événements `cospend_bill_added`, `cospend_bill_updated`, `cospend_bill_deleted` ;
  diagnostics ; traductions FR/EN ; `categories: finance` ; Home Assistant 2026.11.0 minimum.
- aiocospend 0.2.0 : `ProjectBills` (cache des dépenses et synchronisation incrémentale),
  `ProjectStatistics.paid_in` / `spent_in` ; l'égalité des dépenses ignore `project_id`.
- Workflow manuel de publication de `aiocospend` sur PyPI.
- Jalon M1 : client `aiocospend` 0.1.0 (connexion et contrôle de version, projets, lecture
  paginée et incrémentale des dépenses, création, modification partielle, suppression, statistiques,
  plan de remboursement), modèles typés, exceptions typées, faux serveur Cospend pour les tests,
  test de contrat sur un vrai serveur.
- Correction (relevée par le test de contrat) : les statistiques sont lues même quand PHP renvoie
  une liste au lieu d'un objet (dépenses sans catégorie ou sans mode de paiement).
- Correction : le workflow de contrat ne collecte plus que `tests/contract` (il échouait faute de
  Home Assistant dans cet environnement).
- CI : tests du client séparés de ceux de l'intégration ; actions GitHub passées en v7.
- Jalon M0 : structure du dépôt, intégration vide, client `aiocospend` vide, squelette de la carte,
  intégration continue, serveur de test Nextcloud + Cospend en conteneur.
