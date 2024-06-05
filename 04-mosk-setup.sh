#!/bin/bash

# Set the necessary variables
NAMESPACE=""
MOSK_RELEASE=""

# Path to the SSH public key
SSH_KEY_PATH="$HOME/.ssh/id_rsa.pub"

# Check if the required variables are set
if [[ -z "$NAMESPACE" || -z "$MOSK_RELEASE" || ! -f "$SSH_KEY_PATH" ]]; then
  echo "Error: Required variables are not set or files are missing."
  echo "Please ensure NAMESPACE, MOSK_RELEASE are defined and SSH key exists at $SSH_KEY_PATH."
  exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Read KVM_NODE_IP from hosts.txt file
if [ ! -f "${SCRIPT_DIR}/hosts.txt" ]; then
  echo "Error: hosts.txt file not found."
  exit 1
fi
KVM_NODE_IP=$(cat ${SCRIPT_DIR}/hosts.txt)

# Function to replace variables in files
replace_in_files() {
  local search=$1
  local replace=$2
  local file_pattern=$3

  find "${SCRIPT_DIR}/mosk" -type f -name "${file_pattern}" -exec sed -i "s/${search}/${replace}/g" {} \;
}

# Replace variables in the mosk directory files
replace_in_files "SET_NAMESPACE" "$NAMESPACE" "*"
replace_in_files "KVM_NODE_IP" "$KVM_NODE_IP" "*"
replace_in_files "SET_SSH_KEY" "$(cat $SSH_KEY_PATH)" "02-ssh-key.yaml"
replace_in_files "SET_MOSK_RELEASE" "$MOSK_RELEASE" "04-cluster.yaml"

# Apply the Kubernetes configurations with a wait time of 30 seconds between each
apply_kubectl() {
  kubectl apply -f "$1"
  sleep 30
}

apply_kubectl "mosk/01-namespace.yaml"
apply_kubectl "mosk/02-ssh_key.yaml"
apply_kubectl "mosk/02-metallbconfig.yaml"
apply_kubectl "mosk/03-bmh/01-bmh-master.yaml"
apply_kubectl "mosk/03-bmh/02-bmh-cmp-hc.yaml"
apply_kubectl "mosk/04-cluster.yaml"
apply_kubectl "mosk/05-bmhp-cmp.yaml"
apply_kubectl "mosk/05-bmhp-ctl.yaml"
apply_kubectl "mosk/06-l2template.yaml"
apply_kubectl "mosk/07-subnet.yaml"
apply_kubectl "mosk/08-machine/01-machine-ctl.yaml"
apply_kubectl "mosk/08-machine/02-machine-cmp.yaml"
apply_kubectl "mosk/09-kcc.yaml"

echo "MOSK setup script completed successfully."
