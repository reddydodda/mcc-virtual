import os
import subprocess
import time

def run_command(command, check_output=False, shell=True):
    if check_output:
        return subprocess.check_output(command, shell=shell).decode('utf-8').strip()
    else:
        subprocess.run(command, shell=shell, check=True)

def wait_for_condition(command, index, expected_state, timeout=9000, interval=10):
    start_time = time.time()
    while True:
        output = run_command(command, check_output=True)
        lines = output.strip().split("\n")
        header = lines[0].split()
        state_index = header.index(index)
        nodes = lines[1:]
        node_states = [node.split()[state_index] for node in nodes]
        if all(state == expected_state for state in node_states):
            return True
        elapsed_time = time.time() - start_time
        if elapsed_time > timeout:
            raise Exception(f"Timed out waiting for condition: {command}")
        print(f"Waiting for condition: {expected_state}. Current status: {node_states}")
        time.sleep(interval)

# Get the current directory path
current_dir = os.path.dirname(os.path.abspath(__file__))

# Check for the presence of mirantis.lic file
if not os.path.exists("mirantis.lic"):
    print("Error: mirantis.lic file not found.")
    print("Please make sure the mirantis.lic file is present in the current directory before running the script.")
    exit(1)

# Step 1: Run 01-install-vbmc.sh and verify vbmc list
run_command("./01-install-vbmc.sh")
run_command("/opt/vbmc/bin/vbmc list")

# Step 2: Run 02-virt-install.sh --create and verify VMs and vbmc
run_command("./02-virt-install.sh --create")
run_command("virsh list --all")
run_command("/opt/vbmc/bin/vbmc list")

# Step 3: Run 03-bootstrap-templates.sh and verify kaas-bootstrap creation
run_command("./03-bootstrap-templates.sh")
assert os.path.exists("kaas-bootstrap"), "kaas-bootstrap directory not found"

# Step 4: Copy mirantis.lic to kaas-bootstrap/
run_command("cp mirantis.lic kaas-bootstrap/")

# Step 5: Run bootstrap.sh bootstrapv2
run_command("./kaas-bootstrap/bootstrap.sh bootstrapv2")

kubeconfig_path = os.path.expanduser("~/.kube/kind-config-clusterapi")
os.environ["KUBECONFIG"] = kubeconfig_path

# Step 6: Run kubectl create commands
run_command("./kaas-bootstrap/bin/kubectl create -f mcc/bootstrapregion.yaml.template")
run_command("./kaas-bootstrap/bin/kubectl create -f mcc/serviceusers.yaml.template")
run_command("./kaas-bootstrap/bin/kubectl create -f mcc/cluster.yaml.template")
run_command("./kaas-bootstrap/bin/kubectl create -f mcc/baremetalhostprofiles.yaml.template")
run_command("./kaas-bootstrap/bin/kubectl create -f mcc/baremetalhosts.yaml.template")
run_command("./kaas-bootstrap/bin/kubectl create -f mcc/ipam-objects.yaml.template")
run_command("./kaas-bootstrap/bin/kubectl create -f mcc/metallbconfig.yaml.template")
run_command("./kaas-bootstrap/bin/kubectl create -f mcc/machines.yaml.template")

# Step 7: Check bootstrapregions status
wait_for_condition("kubectl get bootstrapregions -o wide", "READY", "true")
time.sleep(30)
wait_for_condition("kubectl get bmh -o wide", "STATE", "available")

# Step 8: Approve bootstrap
run_command("./kaas-bootstrap/container-cloud bootstrap approve all")

# Step 9: Check bmh and lcmmachines status
wait_for_condition("kubectl get bmh -o wide", "STATE", "provisioned")
time.sleep(180)
wait_for_condition("kubectl get lcmmachines -o wide", "STATE", "Ready")

# Step 10: Generate kubeconfig and keycloak creds
run_command("./kaas-bootstrap/container-cloud get cluster-kubeconfig --kubeconfig ~/.kube/kind-config-clusterapi --cluster-name kaas-mgmt")

# Wait for Cluster to be Ready
wait_for_condition("kubectl get cluster -o wide", "READY", "true")

# Save keycloak creds to keycloak.yaml file
keycloak_output = run_command("./kaas-bootstrap/container-cloud get keycloak-creds --mgmt-kubeconfig kubeconfig-kaas-mgmt", check_output=True)
with open("keycloak.yaml", 'w') as file:
    file.write(keycloak_output)

# Export KUBECONFIG environment variable
kubeconfig_file = os.path.join(current_dir, "kubeconfig-kaas-mgmt")
if os.path.exists(kubeconfig_file):
    os.environ["KUBECONFIG"] = kubeconfig_file
else:
    raise Exception(f"Kubeconfig file not found: {kubeconfig_file}")

# Wait for Cluster to be Ready
wait_for_condition("kubectl get cluster -o wide", "READY", "true")

# Delete BootStrap Cluster
run_command("./kaas-bootstrap/bin/kind delete cluster -n clusterapi")

# Step 11: Run 04-mosk-setup.sh
run_command("./04-mosk-setup.sh")

# Step 12: Wait for BMH and lcmmachines in mosk namespace to be Ready
wait_for_condition("kubectl get bmh -o wide -n mosk", "STATE", "provisioned")
time.sleep(180)
wait_for_condition("kubectl get lcmmachines -o wide -n mosk", "STATE", "Ready")
time.sleep(180)

# Wait for Cluster to be Ready
wait_for_condition("kubectl get cluster -o wide -n mosk", "READY", "true")

# Step 13: Check kcc status
#wait_for_condition("kubectl get kcc -o wide -n mosk", "VALIDATION", "Ready")

# Step 14: Generate mosk kubeconfig
namespace = "mosk"
run_command(f"kubectl -n {namespace} get secrets {namespace}-kubeconfig -o jsonpath='{{.data.admin\\.conf}}' | base64 -d | sed 's/:5443/:443/g' | tee mosk.kubeconfig")

# Export KUBECONFIG environment variable
mos_kubeconfig_file = os.path.join(current_dir, "mosk.kubeconfig")
if os.path.exists(mos_kubeconfig_file):
    os.environ["KUBECONFIG"] = mos_kubeconfig_file
else:
    raise Exception(f"Kubeconfig file not found: {mos_kubeconfig_file}")

# Step 15: Check ceph keyrings and health
run_command("kubectl -n openstack-ceph-shared get secrets openstack-ceph-keys -o yaml")
run_command("kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph -s")

# Step 16: Apply osdpl
run_command("kubectl apply -f mosk/10-osdpl/osdpl-secret.yaml")
run_command("kubectl apply -f mosk/10-osdpl/osdpl.yaml")

# Step 17: Check osdpl status
time.sleep(30)
wait_for_condition("kubectl -n openstack get osdplst -o wide", "CONTROLLER", "APPLIED")

# Export KUBECONFIG environment variable
os.environ["KUBECONFIG"] = kubeconfig_file

# Wait for Cluster to be Ready
wait_for_condition("kubectl get cluster -o wide -n mosk", "READY", "true")

print("Deployment completed successfully.")
