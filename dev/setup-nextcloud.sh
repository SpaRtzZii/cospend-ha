#!/usr/bin/env bash
# Attend que Nextcloud soit installé, puis installe l'application Cospend.
set -euo pipefail

cd "$(dirname "$0")"
URL="${COSPEND_TEST_URL:-http://localhost:8080}"

echo "Attente de Nextcloud sur ${URL} (jusqu'à 10 minutes)..."
for _ in $(seq 1 120); do
  if curl -fsS "${URL}/status.php" 2>/dev/null | grep -q '"installed":true'; then
    break
  fi
  sleep 5
done
curl -fsS "${URL}/status.php" | grep -q '"installed":true' || { echo "Nextcloud n'a pas démarré." >&2; exit 1; }

echo "Installation de l'application Cospend..."
docker compose exec -T -u www-data nextcloud php occ app:install cospend \
  || docker compose exec -T -u www-data nextcloud php occ app:enable cospend

docker compose exec -T -u www-data nextcloud php occ app:list | grep -i cospend
echo
echo "Prêt. Variables pour les tests de contrat :"
echo "  export COSPEND_TEST_URL=${URL}"
echo "  export COSPEND_TEST_USER=admin"
echo "  export COSPEND_TEST_PASSWORD=admin-test-password"
