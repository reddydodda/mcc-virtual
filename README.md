# MCC Bootstrap Setup

This guide provides step-by-step instructions for setting up a bare metal server and bootstrapping a MCC environment.

## Prerequisites

1. **Baremetal Server Requirements:**
   - Minimum 256 GB memory
   - Minimum 32 cores CPU
   - Minimum 1 TB storage

2. **Operating System:**
   - Ubuntu 20.04

3. **Clone the Repository:**
   ```bash
   git clone http://github.com/reddydodda/mcc-virtual.git
   cd mcc-virtual/
   ```

## Automated Deployment Script

The Python script mcc-mosk.py will automates the entire deployment process of MCC and MOSK without any manual steps.

### Steps to Use `mcc-mosk.py`:

```bash
python3 mcc-mosk.py
```


## Manual Steps for deploying MCC

### 1. Run the VBMC Script

1. Ensure the `hosts.txt` file contains the IP address of your KVM node.
2. Run the `vbmc` script to create virtual bridges and configure Virtual BMC.

```bash
./01-install-vbmc.sh
```

### 3. Run Virt Install

```bash
./02-virt-install.sh --create
```

### 4. Run Bootstrap Script

```bash
./bootstrap_node.sh
```

### 5. Reboot the Node

```bash
sudo reboot
```

### 6.  Run Bootstrap Process


  i. Update/Replace mirantis.lic file at kaas-bootstrap/mirantis.lic.

  
  ii. Navigate to the kaas-bootstrap directory.

   ```bash
   cd kaas-bootstrap
   ```
 iii. Execute the bootstrap script.

   ```bash
   ./bootstrap.sh bootstrapv2
   ```

### 7. Apply Templates to Bootstrap

 i. Apply the necessary templates using kubectl.

   ```bash
   export KUBECONFIG=~/.kube/kind-config-clusterapi

   ./kaas-bootstrap/bin/kubectl create -f mcc/bootstrapregion.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f mcc/serviceusers.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f mcc/cluster.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f mcc/baremetalhostprofiles.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f mcc/baremetalhosts.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f mcc/ipam-objects.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f mcc/metallbconfig.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f mcc/machines.yaml.template
   ```

### 8. Monitor the Process

  ```bash
  kubectl get bmh -o go-template='{{- range .items -}} {{.status.provisioning.state}}{{"\n"}} {{- end -}}'

  kubectl get bootstrapregions -o go-template='{{(index .items 0).status.ready}}{{"\n"}}'

  kubectl get bootstrapregions -o go-template='{{(index .items 0).status.conditions}}{{"\n"}}'
  ```

### 9. Approve the Changes

  BMH node status should be `available` before approving bootstrap

  ```bash
  ./kaas-bootstrap/container-cloud bootstrap approve all
  ```

### 10. Check Machine Status

 ```bash
 kubectl get bmh -o wide
 kubectl get lcmmachines -o wide
 ```

### 11. Generate Kubeconfig File

  i. Once lcmmachine is in Ready state, generate the kubeconfig file for the MCC cluster.

  ```bash
  ../kaas-bootstrap/container-cloud get cluster-kubeconfig --kubeconfig ~/.kube/kind-config-clusterapi --cluster-name kaas-mgmt
  ```
  
  ii. Generate Keycloak credentials.

  ```bash
  ../kaas-bootstrap/container-cloud get keycloak-creds --mgmt-kubeconfig kubeconfig
  ```

### 12.  Delete the Cluster (Optional)

 ```bash
 ./bin/kind delete cluster -n clusterapi
 ```

## Create MOSK Cluster

### 1. Create mosk cluster templates

 ```bash
 ./04-mosk-setup.sh
 ```

### 2. Check BMH and Machine Status

 ```bash
 watch "kubectl get bmh -o wide -A ; kubectl get lcmmachines -o wide -A"
 ```

### 3. Check KAAS Ceph Cluster ( KCC ) Status

 ```bash
 kubectl get kcc -o wide -A
 ```

### 4. Once Nodes and KCC are in Ready state generate MOSK cluster Kubeconfig 

 ```bash
 kubectl -n {NAMESPACE}  get secrets {NAMESPACE}-kubeconfig -o jsonpath='{.data.admin\.conf}' | base64 -d | sed 's/:5443/:443/g' | tee mosk.kubeconfig
 ```

### 5. Check for ceph keyrings and ceph health before applying MOSK OSDPL templates

 ```bash
 kubectl -n openstack-ceph-shared get secrets openstack-ceph-keys -o yaml

 kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph -s
 ```

### 6. Apply OSDPL secrets and OSDPL object

 ```bash
 kubectl apply -f mosk/10-osdpl/osdpl-secret.yaml

 kubectl apply -f mosk/10-osdpl/osdpl.yaml
 ```

### 7. Check for OSDPL status 

 ```bash
 kubectl -n openstack get osdplst -o wide
 ```


### Cleanup

1. To clean up the VMs and associated resources, run the following script:

```bash
./manage_vms.sh --cleanup
```
