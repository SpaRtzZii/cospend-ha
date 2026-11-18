# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage [SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté
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
