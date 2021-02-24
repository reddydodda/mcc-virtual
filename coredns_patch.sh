#!/bin/bash

kubectl -n coredns patch service coredns-coredns --type='json' -p='[{"op": "replace", "path": "/spec/ports", "value": [{"name": "udp-53", "port": 53, "protocol": "UDP", "targetPort": 53}]}]'
kubectl -n coredns patch service coredns-coredns --type='json' -p='[{"op": "replace", "path": "/spec/type", "value":"LoadBalancer"}]'
