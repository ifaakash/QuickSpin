# Kubernetes Notes

Kubernetes learning notes from the QuickSpin k3d/k3s cluster: each one explains a concept or an incident.

## Table of contents

| # | Doc | What it explains | Analogy | Date |
|---|---|---|---|---|
| 1 | [How kubectl talks to Kubernetes](k8s-apiserver-kubectl-architecture-README.md) | API server, kubeconfig, the "everything goes through the API server" rule, plus the `connection refused` incident (k3d serverlb down) | Restaurant: waiter, order book, managers, cooks | 2026-11-05 |
| 2 | [k3s: App → MySQL connectivity](k3s-db-connectivity-README.md) | Services, label selectors, ConfigMap vs Secret: six stacked bugs between the app and the DB | — | 2026-09-24 |

## Writing rules for new docs

- Start with a **one-sentence core idea**.
- Use **one analogy** and stick to it.
- Cover only the components you need to understand the idea.
- End with a **"Remember this"** box of 3 lines or fewer.
- Add a row to the table above.
