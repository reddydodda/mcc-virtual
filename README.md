
1. Download trail Licence for MCC:

    https://www.mirantis.com/software/docker/docker-enterprise-container-cloud/download/

2. Install Docker

```shell
sudo apt install docker.io

sudo usermod -aG docker $USER
```

## KAAS Cluster

```shell

1. git clone https://github.com/reddydodda/mcc-virtual.git

2. cd mcc-virtual/

3. update hots file with KVM machines

   vim scripts/hosts

   172.16.98.10
   172.16.98.11

4.  Install vbmc on KVM machines

   ./scripts/install_vbmc.sh

5. ./scripts/virt_mcc.sh

6. ./scrpts/virt_ceph.sh ( optional )

7. genrate templates for MCC

   source variable_export.sh
   ./mcc_templates.sh

8. ./bootstrap.sh preflight

9. ./bootstrap.sh all

10. get machine status

   kubectl --kubeconfig ~/.kube/kind-config-clusterapi get bmh -o wide

11. get KAAS UI from 

kubectl -n kaas get svc kaas-kaas-ui

```

## MOSK Changes

```shell

1. genrate templates for mosk 

  cd mcc-virtual/
      
  ./mosk_templates.sh 
  ./mosk_ceph_templates.sh  
 
2. Create NS and keys

export KUBECONFIG=$HOME/kaas-bootstrap/kubeconfig
kubectl create ns ${CHILD_NAMESPACE}

kubectl get publickey -o yaml bootstrap-key | sed 's|namespace: default|namespace: ${CHILD_NAMESPACE}|' | kubectl apply -f -

kubectl get baremetalhostprofile -o yaml | sed 's|namespace: default|namespace: ${CHILD_NAMESPACE}|' | sed 's|name: region-one-default|name: region-one-${CHILD_NAMESPACE}|' | kubectl apply -f -

kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/l2template.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/subnet.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/cephhostprofile.yaml

2. Create baremetalhosts and wait until they got ready state

kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-master.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-worker-ctl.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-worker-cmp.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml

Note: Check status


watch -n 10 "kubectl get bmh -A; kubectl get lcmmachines -A -o wide"


3. Then create cluster and machines:

kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/machines-master.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/machines-worker-ctl.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/machines-worker-cmp.yaml
kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml

4. Create a ceph cluster on top of the existing Kubernetes cluster:

kubectl apply -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml

5. Wait until all resources are up and running on the child cluster. Check if secret with OpenStack ceph keyrings exists on child cluster:
( You can download the kubeconfig file form the KaaS UI )

kubectl get secret -n openstack-ceph-shared openstack-ceph-keys

```

## OpenStack Deployment

1. kubectl -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/01-core-ceph-local-non-dvr.yaml

2. Wait till all pods in openstack namespace are running

	export KUBECONFIG=MOSK_TOKEN

        kubectl get pods -n openstack

3. update 02-coredns.yaml with ingress SVC IP and domain name

```shell
        ip=$(kubectl -n openstack get services ingress -o json | jq -r .status.loadBalancer.ingress[0].ip)

        sed -i "s|1.2.3.4|${ip}|" 02-coredns.yaml

        sed -i "s|it.just.works|mosk.local|" 02-coredns.yaml
```

3. kubectl -f $HOME/kaas-bootstrap/${CHILD_NAMESPACE}/02-coredns.yaml

4. apply coredns patch

        ./coredns_patch.sh

5. update configmap of dns

```shell
kubectl get configmap -n kube-system coredns -o yaml
apiVersion: v1
data:
  Corefile: |
    .:53 {
        errors
        health
        ready
        kubernetes cluster.local in-addr.arpa ip6.arpa {
          pods insecure
          fallthrough in-addr.arpa ip6.arpa
        }
        prometheus :9153
        forward . /etc/resolv.conf
        cache 30
        loop
        reload
        loadbalance
    }
    mosk.local:53 {
        errors
        cache 30
        forward . 10.233.172.192
    }
```

6. update DNS records

```shell
##NTT
172.16.30.35 barbican.mosk.local
172.16.30.35 cinder.mosk.local
172.16.30.35 cloudformation.mosk.local
172.16.30.35 designate.mosk.local
172.16.30.35 glance.mosk.local
172.16.30.35 heat.mosk.local
172.16.30.35 horizon.mosk.local
172.16.30.35 keystone.mosk.local
172.16.30.35 neutron.mosk.local
172.16.30.35 nova.mosk.local
172.16.30.35 novncproxy.mosk.local
172.16.30.35 octavia.mosk.local
172.16.30.35 placement.mosk.local
```

7.  get keystone password

	kubectl -n openstack get secret keystone-keystone-admin -ojsonpath='{.data.OS_PASSWORD}' | base64 -d


