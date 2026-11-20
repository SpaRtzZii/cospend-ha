# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage [SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté (jalon M7b : statistiques)
- Bouton « Statistiques » dans la carte (option `show_stats`, active par défaut) : tableau (par
  membre : payé, part, solde ; par catégorie, mode de paiement et mois), graphiques (dépenses par
  mois empilées par catégorie, dépenses par catégorie) et diagramme de Sankey (payeur → catégorie
  → bénéficiaire).
- Filtres : période (mois, mois dernier, 30 jours, année, dates libres), payé par, pour,
  catégorie, mode de paiement, inclusion des remboursements (exclus par défaut).
- Commande websocket `cospend/statistics`. Les totaux sont calculés localement sur les dépenses
  synchronisées (pas d'appel à Nextcloud), donc disponibles hors ligne ; les mois sont lus dans le
  fuseau de Home Assistant.
- Bibliothèque `aiocospend` 0.8.0 : `compute_statistics`, `StatsFilter` et modèles associés.

### Ajouté (jalon M7a : plan de remboursement)
- Bouton « Remboursements » dans la carte (option `show_settlement`, active par défaut) : plan de
  Cospend (qui doit combien à qui), vos remboursements en premier, avec avertissement quand des
  opérations sont en attente. Hors Nextcloud, le plan est calculé localement.
- « Rembourser » enregistre la dépense correspondante (payée par le débiteur, au profit du
  créditeur, catégorie Remboursement) après confirmation ; mise en file d'attente hors ligne.
- Commande websocket `cospend/settlement`.
- Bibliothèque `aiocospend` 0.7.0 : `suggest_settlement` (plan local, en centimes) et prise en
  charge de la catégorie Remboursement (−11) à la création d'une dépense.
- Catégorie −11 à la création : acceptée par un serveur réel (vérifié).

### Corrigé (M7a)
- Dépenses affichées un jour trop tôt (J-1) : le serveur renseigne `date` en UTC, alors que Cospend
  affiche l'horodatage dans le fuseau de l'utilisateur. Le jour est désormais calculé depuis
  l'horodatage dans le fuseau de Home Assistant (carte, capteur, événements).

### Corrigé (M6c, d'après les essais sur serveur réel)
- Nouvelle option de carte `allow_manage` (case dans l'éditeur visuel) : cochée, la roue crantée
  des réglages du projet est ouverte à tous les utilisateurs de Home Assistant ; décochée (défaut),
  elle est réservée aux administrateurs. Le niveau gestionnaire Nextcloud reste exigé.
- Serveur injoignable pendant une gestion de projet : message clair (« non mise en file d'attente »)
  au lieu de l'erreur réseau brute.
- Modification d'une catégorie, d'un mode de paiement ou d'une devise : erreur HTTP 400. Cospend
  attend l'objet complet (nom, icône et couleur ; nom et taux) : les services renvoient désormais
  l'état actuel complété par les changements. Même principe pour un membre, dont la couleur
  changeait à la réactivation (poids et couleur actuels conservés).
- Création d'une catégorie, d'un mode de paiement ou d'une devise : erreur 404. Cospend nomme ces
  routes au singulier (`category`, `paymentmode`, `currency`) ; la bibliothèque les essaie dans
  cet ordre puis retente l'autre forme sur un 404. `aiocospend` 0.6.1.
- Ajouter un membre portant le nom d'un membre désactivé le **réactive** (avec un message dédié)
  au lieu d'échouer ; un membre actif du même nom est refusé avec un message clair.
- Les données sont resynchronisées après chaque opération de gestion, même en cas d'erreur
  (une requête peut avoir abouti côté Nextcloud), au lieu d'attendre le prochain rafraîchissement.
- Les erreurs « requête refusée » (HTTP 400) reprennent le message renvoyé par Cospend.

### Ajouté (jalon M6c : gestion du projet)
- Roue crantée dans la carte (niveau gestionnaire requis, masquée avec `allow_write: false`) :
  écran à quatre onglets pour ajouter, modifier et supprimer les **membres** (nom, poids, couleur,
  actif), les **catégories** et **modes de paiement** (nom, icône, couleur) et les **devises**
  (code, taux de change), avec confirmation avant suppression.
- 12 services : `add_member`, `update_member`, `delete_member`, `add_category`, `update_category`,
  `delete_category`, `add_payment_mode`, `update_payment_mode`, `delete_payment_mode`,
  `add_currency`, `update_currency`, `delete_currency`. Les éléments se désignent par leur nom ou
  leur identifiant.
- Bibliothèque `aiocospend` 0.6.0 : appels `create_/update_/delete_` pour ces quatre objets.
- Ces opérations ne passent pas par la file d'attente hors ligne : elles échouent si Nextcloud est
  injoignable (rejouer plus tard un ajout ou une suppression pourrait créer des doublons).
- À vérifier sur un vrai serveur : routes et paramètres écrits d'après l'API connue de Cospend, non
  testés contre Nextcloud. Un membre qui a des dépenses est désactivé par Cospend, pas supprimé.

### Ajouté (jalon M6b : modification, répartitions, devises, répétition)
- Bouton « Modifier » dans le détail d'une dépense : formulaire prérempli, seuls les champs
  changés sont envoyés (la date inchangée n'est pas renvoyée, pour ne pas perdre l'heure).
- Création avec répartition par **montants** ou par **pourcentages** (total des parts contrôlé).
- Montant dans une **devise étrangère** (taux repris du projet, modifiable, aperçu de la
  conversion) ; la devise d'origine est reprise à la modification.
- **Répétition** (jour, semaine, mois, année…, fréquence, date de fin, tous les membres actifs).
- Service `update_bill` : nouveaux champs `currency`, `exchange_rate`, `repeat`,
  `repeat_frequency`, `repeat_until`, `repeat_all_active`. Bibliothèque `aiocospend` 0.5.0.
- Limites : le montant, les participants et la devise d'une répartition personnalisée ne se
  modifient pas (supprimer puis recréer) ; modifier une dépense aux poids inégaux remet les poids
  à égalité (la carte prévient) ; l'effacement de la date de fin de répétition reste à vérifier
  sur un vrai serveur.

### Ajouté (jalon M6a : écriture depuis la carte)
- Bouton « Ajouter une dépense » : formulaire avec titre, montant ou calcul (aperçu du résultat),
  payeur (par défaut le membre du même nom que l'utilisateur connecté), participants, date,
  catégorie, mode de paiement et commentaire, en répartition égale.
- Suppression d'une dépense depuis son détail, avec confirmation (corbeille de Nextcloud ;
  une répartition personnalisée est supprimée en entier).
- Hors ligne, l'opération passe par la file d'attente et la carte le dit.
- Option `allow_write` (case dans l'éditeur visuel) pour une carte en lecture seule.

### Corrigé (carte)
- Icônes de catégories : les remboursements affichent 💰 (catégorie interne −11 de Cospend), la
  pastille prend la couleur de la catégorie, et une dépense sans catégorie reçoit une icône neutre
  au lieu d'un faux pictogramme.

### Ajouté (jalon M5 : carte Lovelace en lecture)
- Carte `custom:cospend-card`, servie par l'intégration (aucune ressource à déclarer) et compilée
  à la publication d'une release. Elle affiche : sélecteur de projet (archivés masqués), soldes des
  membres en barres, liste des dépenses par date avec pagination, recherche, détail d'une dépense
  avec la part de chacun, montant d'origine en devise étrangère, répétition, opérations en attente
  du mode hors ligne et alerte quand Nextcloud est injoignable.
- Thème : la carte n'utilise que les variables de thème de Home Assistant (clair, sombre,
  thèmes personnalisés). Français et anglais.
- Éditeur visuel : titre, projet, blocs affichés et taille de page.
- API websocket de l'intégration (`cospend/projects`, `cospend/bills`, `cospend/bill`,
  `cospend/subscribe`) : lecture seule, sans appel réseau vers Nextcloud, répartitions
  personnalisées regroupées, mise à jour poussée à la carte.
- L'intégration dépend maintenant de `http` et `websocket_api`.

### Ajouté (connexion par IP locale)
- L'assistant de configuration propose deux choix : **adresse web** (http / https) ou **adresse IP
  locale + port** (avec une case « Utiliser HTTPS »). La reconfiguration propose les mêmes choix et
  permet de passer du nom de domaine à l'IP, et inversement, sans perdre les projets suivis.
- Nouvelles erreurs claires : adresse IP / port invalide, et « domaine non approuvé » (Nextcloud
  répond 400 tant que l'adresse n'est pas dans `trusted_domains`).
- Les entrées existantes continuent de fonctionner telles quelles.

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
