# How kubectl Talks to Kubernetes (2026-11-05)

## Core idea

**Everything goes through the API server.** `kubectl`, the managers and the
nodes all talk only to the API server. They never talk to each other.

## The analogy: a restaurant

| Restaurant | Kubernetes | Job |
|---|---|---|
| Customer | `kubectl` | Places orders and asks questions |
| Address + membership card in your wallet | kubeconfig (`~/.kube/config`) | Where the restaurant is and proof of who you are |
| Front door | k3d `serverlb` container | The way in from your Mac (k3d only) |
| Waiter | **API server** | The **only** one who takes orders and writes in the book |
| Order book | etcd (datastore) | The single source of truth: what *should* exist |
| Managers | scheduler + controllers | Read the book and assign work |
| Cooks | kubelet (one per node) | Do the work they're assigned: run the containers |

```
 Customer        Door           Waiter          Order book
 kubectl ──────► serverlb ────► API server ◄──► etcd
                                   ▲  ▲
                    "anything new?"│  │"anything for me?"
                                   │  │
                            Managers  Cooks (kubelet on each node)
```

Managers and cooks don't wait to be told. They **keep asking the waiter**
"anything new for me?" and act on what they see.

## What happens on `kubectl get nodes`

1. kubectl opens your kubeconfig to find the address and your ID card.
2. It walks through the front door (serverlb) to the waiter (API server).
3. The waiter checks your ID: who you are, and whether you're allowed to ask this.
4. The waiter reads the order book and hands you the answer.

It's just a question, so no cook is involved.

## What happens on `kubectl apply -f deployment.yml`

1. The waiter writes "I want 3 copies of this app" in the order book, then **replies right away**.
   At this point nothing is running yet.
2. A manager notices the new order and decides which cook (node) gets each copy.
3. Each cook sees its new assignment and starts the containers.
4. The cooks report back "done", and the waiter updates the book.

This is why Kubernetes is called **declarative**. You write down *what you want*,
and the managers and cooks keep working until reality matches the book.

## Our incident: the front door was locked

**Symptom**
```
The connection to the server 0.0.0.0:58699 was refused
```

**What was actually going on**
```
kubectl ──► 0.0.0.0:58699 ──X  serverlb (DEAD)     API server ✅  nodes ✅
```
The kitchen and the waiter were working fine, but the front door was locked.
The k3d `serverlb` container had been killed weeks earlier (exit code 137 = force-killed).
The order never got past the door.

**How we checked**
```bash
k3d cluster list                                         # cluster and node counts
docker ps -a --filter "name=k3d"                          # serverlb showed "Exited"
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'   # which address kubectl uses
```

**Fix**
```bash
docker start k3d-mac-serverlb        # or: k3d cluster start mac
# if the port changed, refresh the address in your kubeconfig:
k3d kubeconfig merge mac --kubeconfig-merge-default --kubeconfig-switch-context
kubectl get nodes
```

## Read the error by where it stopped

| Where it stopped | Error you see | Restaurant |
|---|---|---|
| At the door | `connection refused` / timeout | Door locked or wrong address |
| At the ID check | `401 Unauthorized` / `403 Forbidden` | Card invalid / not allowed to order that |
| In the kitchen | `kubectl get nodes` works, node is `NotReady` | Waiter is fine, but a cook stopped answering |

## Try it yourself

```bash
kubectl get nodes -v=8     # see the real HTTP request kubectl sends to the waiter
```

**Question to think about:** if the waiter (API server) goes home, do the cooks
stop cooking the dishes already on the stove? (Do running pods keep serving traffic?)

## Remember this

> **Everyone talks only to the waiter (API server). Nobody talks to each other.**
> `kubectl` just writes an order in the book. The managers and cooks make it real.
> `connection refused` = you never got through the door. Check the address and the door first.
