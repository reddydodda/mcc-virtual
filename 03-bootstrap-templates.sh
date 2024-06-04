#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Read KVM_NODE_IP from hosts.txt file
KVM_NODE_IP=$(cat ${SCRIPT_DIR}/hosts.txt)

wget https://binary.mirantis.com/releases/get_container_cloud.sh
chmod 0755 get_container_cloud.sh
./get_container_cloud.sh

# Step 2: Update bootstrap.env file
BOOTSTRAP_ENV_FILE="${SCRIPT_DIR}/kaas-bootstrap/bootstrap.env"

if [ -f "${BOOTSTRAP_ENV_FILE}" ]; then
  cat <<EOF > ${BOOTSTRAP_ENV_FILE}
export KAAS_BM_ENABLED="true"
export KAAS_BM_PXE_IP="192.168.122.2"
export KAAS_BM_PXE_MASK="24"
export KAAS_BM_PXE_BRIDGE="br-pxe"
EOF
else
  echo "bootstrap.env file not found at ${BOOTSTRAP_ENV_FILE}"
fi

# Step 3: Update SET_KVM_ADDRESS in baremetalhosts.yaml.template
BM_TEMPLATE_FILE="${SCRIPT_DIR}/bm/baremetalhosts.yaml.template"

if [ -f "${BM_TEMPLATE_FILE}" ]; then
  sed -i "s/SET_KVM_ADDRESS/${KVM_NODE_IP}/g" ${BM_TEMPLATE_FILE}
else
  echo "baremetalhosts.yaml.template file not found at ${BM_TEMPLATE_FILE}"
fi

echo "Bootstrap script completed successfully."
