"""Client asynchrone pour l'API OCS de Nextcloud Cospend."""

from .client import CospendClient
from .const import MIN_COSPEND_VERSION
from .exceptions import (
    CospendAuthenticationError,
    CospendBadRequestError,
    CospendConnectionError,
    CospendError,
    CospendForbiddenError,
    CospendMaintenanceError,
    CospendNotFoundError,
    CospendResponseError,
    CospendServerError,
    CospendSSLError,
    CospendVersionError,
)
from .models import (
    Bill,
    BillsPage,
    Category,
    Currency,
    Member,
    MemberStats,
    Ower,
    PaymentMode,
    Project,
    ProjectStatistics,
    ServerInfo,
    Settlement,
    Share,
    Transaction,
)
from .utils import compare_versions, format_amount, normalize_url, parse_version

__version__ = "0.1.0"

__all__ = [
    "MIN_COSPEND_VERSION",
    "Bill",
    "BillsPage",
    "Category",
    "CospendAuthenticationError",
    "CospendBadRequestError",
    "CospendClient",
    "CospendConnectionError",
    "CospendError",
    "CospendForbiddenError",
    "CospendMaintenanceError",
    "CospendNotFoundError",
    "CospendResponseError",
    "CospendSSLError",
    "CospendServerError",
    "CospendVersionError",
    "Currency",
    "Member",
    "MemberStats",
    "Ower",
    "PaymentMode",
    "Project",
    "ProjectStatistics",
    "ServerInfo",
    "Settlement",
    "Share",
    "Transaction",
    "__version__",
    "compare_versions",
    "format_amount",
    "normalize_url",
    "parse_version",
]
