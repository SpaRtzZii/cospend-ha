"""Exceptions du client Cospend."""

from __future__ import annotations


class CospendError(Exception):
    """Erreur de base du client Cospend."""

    def __init__(self, message: str = "", *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class CospendConnectionError(CospendError):
    """Serveur injoignable : réseau, délai dépassé, DNS."""


class CospendSSLError(CospendConnectionError):
    """Échec de la vérification du certificat TLS."""


class CospendAuthenticationError(CospendError):
    """Identifiants refusés (HTTP 401) : mot de passe d'application à renouveler."""


class CospendForbiddenError(CospendError):
    """Accès refusé à la ressource (HTTP 403), par exemple droits insuffisants."""


class CospendNotFoundError(CospendError):
    """Ressource introuvable (HTTP 404)."""


class CospendBadRequestError(CospendError):
    """Requête refusée par le serveur (HTTP 400). Le message du serveur est souvent vide."""


class CospendMaintenanceError(CospendError):
    """Serveur en maintenance (HTTP 503) : nouvel essai possible plus tard."""


class CospendServerError(CospendError):
    """Erreur interne du serveur (HTTP 5xx hors 503)."""


class CospendResponseError(CospendError):
    """Réponse inattendue : pas du JSON, enveloppe OCS absente, champ obligatoire manquant."""


class CospendVersionError(CospendError):
    """Version de Cospend trop ancienne ou application Cospend absente."""
