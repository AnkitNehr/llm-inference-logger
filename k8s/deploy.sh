#!/usr/bin/env bash
# k8s/deploy.sh — build images, load them into a self-hosted cluster, apply manifests.
#
# Supports: kind, minikube, k3s (auto-detected). Run from the repo root or k8s/.
#
# Usage:
#   ./k8s/deploy.sh              # build + load + apply everything
#   ./k8s/deploy.sh --apply-only  # skip build, just apply manifests
#   ./k8s/deploy.sh --teardown    # delete namespace + all resources
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO_ROOT"

IMAGES=(
  "ollive/chatbot-api:dev|chatbot_api/Dockerfile|."
  "ollive/ingestion-api:dev|ingestion_api/Dockerfile|."
  "ollive/frontend:dev|frontend/Dockerfile|./frontend"
)

detect_cluster() {
  if command -v kind >/dev/null 2>&1 && kind get clusters 2>/dev/null | grep -q .; then
    echo "kind"; return
  fi
  if command -v minikube >/dev/null 2>&1 && minikube status >/dev/null 2>&1; then
    echo "minikube"; return
  fi
  if command -v k3s >/dev/null 2>&1; then
    echo "k3s"; return
  fi
  if kubectl config current-context >/dev/null 2>&1; then
    echo "generic"; return
  fi
  echo "none"
}

load_image() {
  local image=$1 cluster=$2
  case "$cluster" in
    kind)     kind load docker-image "$image" ;;
    minikube) minikube image load "$image" ;;
    k3s)      docker save "$image" | sudo k3s ctr images import - ;;
    *)        echo "  (skipping load — push '$image' to a registry your cluster can reach)" ;;
  esac
}

case "${1:-}" in
  --teardown)
    kubectl delete namespace ollive --ignore-not-found
    exit 0
    ;;
esac

CLUSTER=$(detect_cluster)
echo "==> Detected cluster: $CLUSTER"
[ "$CLUSTER" = "none" ] && { echo "ERROR: no local k8s cluster found. Install kind / minikube / k3s first."; exit 1; }

if [ "${1:-}" != "--apply-only" ]; then
  echo "==> Building images..."
  for entry in "${IMAGES[@]}"; do
    IFS='|' read -r image dockerfile context <<< "$entry"
    echo "    docker build -t $image -f $dockerfile $context"
    docker build -t "$image" -f "$dockerfile" "$context"
  done
  echo "==> Loading images into $CLUSTER..."
  for entry in "${IMAGES[@]}"; do
    IFS='|' read -r image _ _ <<< "$entry"
    load_image "$image" "$CLUSTER"
  done
fi

echo "==> Applying manifests..."
kubectl apply -k k8s/base/

echo "==> Waiting for rollouts (timeout 180s each)..."
kubectl -n ollive rollout status deploy/postgres           --timeout=180s
kubectl -n ollive rollout status deploy/redis              --timeout=60s
kubectl -n ollive rollout status deploy/ingestion-api      --timeout=120s
kubectl -n ollive rollout status deploy/ingestion-consumer --timeout=120s
kubectl -n ollive rollout status deploy/chatbot-api        --timeout=120s
kubectl -n ollive rollout status deploy/frontend           --timeout=120s

cat <<EOF

==> All deployments ready.

Browser-reachable URLs (assuming NodePort 30xxx works on your cluster):
  UI         http://localhost:30173
  Chatbot    http://localhost:30001
  Ingestion  http://localhost:30002

If NodePorts aren't reachable (some kind/minikube setups), port-forward instead:
  kubectl -n ollive port-forward svc/frontend            5173:5173 &
  kubectl -n ollive port-forward svc/chatbot-api         8001:8001 &
  kubectl -n ollive port-forward svc/ingestion-api       8002:8002 &
Then open http://localhost:5173 — but ALSO rebuild the frontend image with
VITE_CHATBOT_URL=http://localhost:8001 and VITE_INGESTION_URL=http://localhost:8002
so the browser hits the right ports.

To set real API keys:
  kubectl -n ollive create secret generic ollive-secrets \\
    --from-literal=GEMINI_API_KEY=... \\
    --from-literal=POSTGRES_USER=ollive \\
    --from-literal=POSTGRES_PASSWORD=ollive \\
    --from-literal=POSTGRES_DB=ollive \\
    --from-literal=DATABASE_URL='postgresql+asyncpg://ollive:ollive@postgres:5432/ollive' \\
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n ollive rollout restart deploy/chatbot-api

Teardown:
  ./k8s/deploy.sh --teardown
EOF
