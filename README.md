# KaaS Bootstrap Setup

This guide provides step-by-step instructions for setting up a bare metal server and bootstrapping a MCC environment.

## Prerequisites

- A bare metal server with at least:
  - 256 GB of memory
  - 32 cores
  - 1 TB of storage

## Steps

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

  i. Navigate to the kaas-bootstrap directory.

   ```bash
   cd kaas-bootstrap
   ```
 ii. Execute the bootstrap script.

   ```bash
   ./bootstrap.sh bootstrapv2
   ```

### 7. Apply Templates to Bootstrap

 i. Apply the necessary templates using kubectl.

   ```bash
   ./kaas-bootstrap/bin/kubectl create -f ../mcc/bootstrapregion.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f ../mcc/serviceusers.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f ../mcc/cluster.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f ../mcc/baremetalhostprofiles.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f ../mcc/baremetalhosts.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f ../mcc/ipam-objects.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f ../mcc/metallbconfig.yaml.template
   ./kaas-bootstrap/bin/kubectl create -f ../mcc/machines.yaml.template
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
  ./container-cloud bootstrap approve all
  ```

### 10. Check Machine Status

 ```bash
 kubectl get bmh -o wide
 kubectl get lcmmachines -o wide
 ```

### 11. Generate Kubeconfig File

  i. Once lcmmachine is in Ready state, generate the kubeconfig file for the MCC cluster.

  ```bash
  ./container-cloud get cluster-kubeconfig --kubeconfig ~/.kube/kind-config-clusterapi --cluster-name kaas-mgmt
  ```
  
  ii. Generate Keycloak credentials.

  ```bash
  ./container-cloud get keycloak-creds --mgmt-kubeconfig kubeconfig
  ```

### 12.  Delete the Cluster (Optional)

 ```bash
 ./bin/kind delete cluster -n clusterapi
 ```

### Cleanup

1. To clean up the VMs and associated resources, run the following script:

```bash
./manage_vms.sh --cleanup
```
