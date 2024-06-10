#!/bin/bash
#set -x
# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Read KVM_NODE_IP from hosts.txt file
KVM_NODE_IP=$(cat ${SCRIPT_DIR}/hosts.txt)

# Function to create VMs
create_vm() {
  local vm_name=$1
  local mac=$2

  sudo virt-install \
    --connect qemu+ssh://root@${KVM_NODE_IP}/system \
    --virt-type=kvm \
    --name=${vm_name} \
    --os-type=linux \
    --os-variant=ubuntu20.04 \
    --ram=32768 \
    --vcpus=8 \
    --disk size=100,path=/var/lib/libvirt/images_new/${vm_name}-disk1.qcow2,bus=sata,format=qcow2 \
    --disk size=50,path=/var/lib/libvirt/images_new/${vm_name}-disk2.qcow2,bus=sata,format=qcow2 \
    --network bridge=br-pxe,model=virtio,mac=${mac} \
    --network bridge=br-lcm,model=virtio \
    --network bridge=br-others,model=virtio \
    --network bridge=br-fip,model=virtio \
    --graphics vnc \
    --boot network,hd \
    --noautoconsole
}

# Function to create VMs with additional disks
create_vm_with_extra_disks() {
  local vm_name=$1
  local mac=$2

  sudo virt-install \
    --connect qemu+ssh://root@${KVM_NODE_IP}/system \
    --virt-type=kvm \
    --name=${vm_name} \
    --os-type=linux \
    --os-variant=ubuntu20.04 \
    --ram=49152 \
    --vcpus=12 \
    --disk size=100,path=/var/lib/libvirt/images_new/${vm_name}-disk1.qcow2,bus=sata,format=qcow2 \
    --disk size=50,path=/var/lib/libvirt/images_new/${vm_name}-disk2.qcow2,bus=sata,format=qcow2 \
    --disk size=50,path=/var/lib/libvirt/images_new/${vm_name}-disk3.qcow2,bus=sata,format=qcow2 \
    --disk size=50,path=/var/lib/libvirt/images_new/${vm_name}-disk4.qcow2,bus=sata,format=qcow2 \
    --network bridge=br-pxe,model=virtio,mac=${mac} \
    --network bridge=br-lcm,model=virtio \
    --network bridge=br-others,model=virtio \
    --network bridge=br-fip,model=virtio \
    --graphics vnc \
    --boot network,hd \
    --noautoconsole
}

# Function to add VM to Virtual BMC
add_to_vbmc() {
  local vm_name=$1
  local port=$2

  sudo /opt/vbmc/bin/vbmc add ${vm_name} --port ${port} --username root --password admin123 --address ${KVM_NODE_IP}
}

# Function to delete VMs
delete_vm() {
  local vm_name=$1

  sudo /opt/vbmc/bin/vbmc stop ${vm_name}
  sudo /opt/vbmc/bin/vbmc delete ${vm_name}
  sudo virsh destroy ${vm_name}
  sudo virsh undefine ${vm_name}
  sudo rm -f /var/lib/libvirt/images_new/${vm_name}-disk*.qcow2
}

# Create VMs
create_vms() {
  # Create mcc VMs
  for i in {1..3}; do
    vm_name="mcc-${i}${i}"
    mac="52:54:00:c5:91:${i}${i}"
    create_vm ${vm_name} ${mac}
    add_to_vbmc ${vm_name} 623${i}
  done

  # Create mosk-ctl VMs
  for i in {1..3}; do
    vm_name="mosk-ctl-${i}${i}"
    mac="52:54:00:c5:92:${i}${i}"
    create_vm ${vm_name} ${mac}
    add_to_vbmc ${vm_name} 624${i}
  done

  # Create mosk-cmp VMs
  for i in {1..3}; do
    vm_name="mosk-cmp-${i}${i}"
    mac="52:54:00:c5:93:${i}${i}"
    create_vm_with_extra_disks ${vm_name} ${mac}
    add_to_vbmc ${vm_name} 625${i}
  done

  # Start Virtual BMC service
  sudo /opt/vbmc/bin/vbmc start $(/opt/vbmc/bin/vbmc list | grep mcc | awk '{print $2}')
  sudo /opt/vbmc/bin/vbmc start $(/opt/vbmc/bin/vbmc list | grep mosk-ctl | awk '{print $2}')
  sudo /opt/vbmc/bin/vbmc start $(/opt/vbmc/bin/vbmc list | grep mosk-cmp | awk '{print $2}')

  # Check power status and power off using ipmitool
  for i in {1..3}; do
    ipmitool -I lanplus -H ${KVM_NODE_IP} -U root -P admin123 -p 623${i} power status
    ipmitool -I lanplus -H ${KVM_NODE_IP} -U root -P admin123 -p 623${i} power off

    ipmitool -I lanplus -H ${KVM_NODE_IP} -U root -P admin123 -p 624${i} power status
    ipmitool -I lanplus -H ${KVM_NODE_IP} -U root -P admin123 -p 624${i} power off

    ipmitool -I lanplus -H ${KVM_NODE_IP} -U root -P admin123 -p 625${i} power status
    ipmitool -I lanplus -H ${KVM_NODE_IP} -U root -P admin123 -p 625${i} power off
  done

  echo "02-virt-install.sh --create completed successfully."
}

# Clean up VMs
cleanup_vms() {
  # Clean up mcc VMs
  for i in {1..3}; do
    vm_name="mcc-${i}${i}"
    delete_vm ${vm_name}
  done

  # Clean up mosk-ctl VMs
  for i in {1..3}; do
    vm_name="mosk-ctl-${i}${i}"
    delete_vm ${vm_name}
  done

  # Clean up mosk-cmp VMs
  for i in {1..3}; do
    vm_name="mosk-cmp-${i}${i}"
    delete_vm ${vm_name}
  done

  echo "02-virt-install.sh --cleanup completed successfully."
}

# Parse arguments
case "$1" in
  --create)
    create_vms
    ;;
  --cleanup)
    cleanup_vms
    ;;
  *)
    echo "Usage: $0 --create | --cleanup"
    exit 1
    ;;
esac
