# Self-hosted Kubernetes deployment

Manifests in [`base/`](base/) deploy the full stack (Postgres, Redis, ingestion API, ingestion consumer, chatbot API, frontend) into a self-hosted cluster — tested against **kind**, **minikube**, and **k3s**.

## TL;DR — one command

```bash
./k8s/deploy.sh
```

That builds the 3 application images, loads them into your local cluster, applies the manifests, waits for all deployments to roll out, and prints the URLs. Re-runs are safe.

To skip the build (manifests-only):

```bash
./k8s/deploy.sh --apply-only
```

To wipe everything:

```bash
./k8s/deploy.sh --teardown
```

## Prerequisites

Pick one of:

| Cluster | Install |
|---|---|
| **kind** | `brew install kind && kind create cluster` |
| **minikube** | `brew install minikube && minikube start` |
| **k3s** | `curl -sfL https://get.k3s.io \| sh -` |

Also need: `docker`, `kubectl`. The deploy script auto-detects which one you have.

## What gets deployed

Namespace: `ollive`.

| Resource | Kind | Replicas | Notes |
|---|---|---|---|
| `postgres` | Deployment + PVC (2Gi) | 1 | `Recreate` strategy (RWO volume). Init schema mounted as ConfigMap. |
| `redis` | Deployment | 1 | Stream backing the event bus. |
| `ingestion-api` | Deployment + Service | **2** | Stateless — horizontally scalable. |
| `ingestion-consumer` | Deployment | 1 | Drain Redis Stream → Postgres. Scale up to parallelize: `kubectl scale deploy/ingestion-consumer --replicas=3 -n ollive`. Each pod's name becomes the unique consumer-group name. |
| `chatbot-api` | Deployment + NodePort `30001` | 1 | Cancellation registry is in-memory → keep at 1 unless you upgrade to Redis pub/sub. |
| `frontend` | Deployment + NodePort `30173` | 1 | Vite dev server. |
| `ingestion-api-external` | NodePort `30002` | — | Browser-side dashboard hits this. |
| `ollive-config` | ConfigMap | — | Non-secret env. |
| `ollive-secrets` | Secret | — | API keys, DB credentials. |

## Browser URLs (default NodePorts)

| Thing | URL |
|---|---|
| Chat UI | http://localhost:30173 |
| Chatbot API + Swagger | http://localhost:30001/docs |
| Ingestion API + Swagger | http://localhost:30002/docs |

If NodePorts aren't directly reachable on your cluster, the script prints `kubectl port-forward` instructions.

## Setting real API keys

The default Secret ships with **blank API keys** so the SDK auto-falls back to the mock provider — everything works end-to-end with zero secrets. To wire in a real provider:

```bash
kubectl -n ollive create secret generic ollive-secrets \
  --from-literal=GEMINI_API_KEY=AIza... \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=POSTGRES_USER=ollive \
  --from-literal=POSTGRES_PASSWORD=ollive \
  --from-literal=POSTGRES_DB=ollive \
  --from-literal=DATABASE_URL='postgresql+asyncpg://ollive:ollive@postgres:5432/ollive' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n ollive rollout restart deploy/chatbot-api
```

## Scaling

```bash
# Scale consumers to drain the queue faster
kubectl -n ollive scale deploy/ingestion-consumer --replicas=5

# Scale ingestion API horizontally
kubectl -n ollive scale deploy/ingestion-api --replicas=4
```

`chatbot-api` is intentionally pinned to 1 replica because the cancellation registry is in-memory. Production: move to Redis pub/sub keyed on `conversation_id`, then remove the pin.

## Troubleshooting

```bash
kubectl -n ollive get pods                          # who's running
kubectl -n ollive logs deploy/chatbot-api --tail=50
kubectl -n ollive logs deploy/ingestion-consumer --tail=50
kubectl -n ollive describe pod <name>                # if Pending/CrashLoopBackOff
kubectl -n ollive port-forward svc/postgres 5432:5432  # then psql in
```

Image pull errors on kind/minikube usually mean the image wasn't loaded into the cluster's node. Re-run `./k8s/deploy.sh` (without `--apply-only`).

## What's NOT here (deliberately)

- **HPA / VPA** — straightforward to add (`autoscaling/v2 HorizontalPodAutoscaler` on CPU). Skipped because the bundled metrics-server isn't standard across all three cluster flavors.
- **Ingress + TLS** — chose NodePort for portability. To use an Ingress, add `nginx` ingress controller and replace the NodePort Services with ClusterIP + an `Ingress` per host.
- **NetworkPolicies** — minimal but real production hardening. Skipped to keep manifests reviewable.
- **PgBouncer** — would sit in front of Postgres at higher write rates. Not needed at demo scale.
- **A real backup strategy** — production: CloudNativePG operator or a sidecar that runs `pg_dump` to object storage on schedule.
