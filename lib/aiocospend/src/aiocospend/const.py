"""Constantes de l'API Cospend, issues des tests sur un serveur réel (Cospend 4.3.0)."""

from __future__ import annotations

from typing import Final

# Version minimale de l'application Cospend (API OCS v1, paramètres en camelCase).
MIN_COSPEND_VERSION: Final = "1.6.1"

API_VERSION: Final = "v1"
OCS_BASE_PATH: Final = "/ocs/v2.php/apps/cospend/api"
CAPABILITIES_PATH: Final = "/ocs/v2.php/cloud/capabilities"

# Catégorie native attribuée par Cospend aux dépenses de remboursement.
REIMBURSEMENT_CATEGORY_ID: Final = -11
# Aucun mode de paiement / aucune catégorie.
NO_PAYMENT_MODE_ID: Final = 0
NO_CATEGORY_ID: Final = 0

# Codes de répétition d'une dépense ("n" = aucune).
REPEAT_NONE: Final = "n"
REPEAT_CODES: Final = ("n", "d", "w", "b", "s", "m", "y")

# Niveaux d'accès à un projet (4 = propriétaire, constaté sur le serveur de test).
ACCESS_LEVEL_OWNER: Final = 4

# Couleur proposée (Cospend en exige une) pour une catégorie ou un mode de paiement.
DEFAULT_COLOR: Final = "#888888"
