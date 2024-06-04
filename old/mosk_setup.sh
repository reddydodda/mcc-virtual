#!/bin/bash

home_dir=$PWD

export KUBECONFIG=$home_dir/kaas-bootstrap/kubeconfig

#kubectl delete -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/cluster.yaml

#kubectl delete -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmh-master.yaml
#kubectl delete -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmh-ctl.yaml
#kubectl delete -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmh-cmp.yaml

#kubectl delete ns $CHILD_NAMESPACE
sleep 30
kubectl create ns $CHILD_NAMESPACE
kubectl get publickey -o yaml bootstrap-key | sed "s|namespace: default|namespace: $CHILD_NAMESPACE|" | kubectl apply -f -
kubectl get publickey -o yaml cdodda | sed "s|namespace: default|namespace: $CHILD_NAMESPACE|" | kubectl apply -f -
kubectl get baremetalhostprofile -o yaml | sed "s|namespace: default|namespace: $CHILD_NAMESPACE|" | sed "s|name: region-one-default|name: default-$CHILD_NAMESPACE|" | kubectl apply -f -
sleep 10
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmhp-master.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmhp-ctl.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmhp-cmp.yaml
sleep 10
kubectl get l2templates -A
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/subnet.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/l2template_master.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/l2template_ctl.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/l2template_cmp.yaml

sleep 10
~/ipmi/ipmi_check.sh ~/ipmi/hosts
sleep 30
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmh-master.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmh-ctl.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/bmh-cmp.yaml
sleep 30
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/cluster.yaml
sleep 30

kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/machines-master.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/machines-ctl.yaml
kubectl apply -f $home_dir/kaas-bootstrap/$CHILD_NAMESPACE/machines-cmp.yaml

