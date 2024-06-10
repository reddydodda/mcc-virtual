#!/bin/bash

# Update and upgrade OS packages
sudo apt update
sudo apt upgrade -y

# Install necessary packages
sudo apt install -y gcc libpq-dev libvirt-dev python3-dev python3-pip python3-venv ipmitool jq wget \
                python3-wheel python3-virtualenv libvirt-daemon-system libvirt-clients bridge-utils docker.io \
                qemu-kvm virtinst virt-manager netcat-openbsd qemu libvirt-clients libvirt-daemon-system

# Add the user to the libvirt and kvm groups
sudo usermod -aG libvirt $(whoami)
sudo usermod -aG kvm $(whoami)

# Get IP address from bond0 and write to hosts.txt
BOND0_IP=$(ip -4 addr show bond0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n 1)
echo "${BOND0_IP}" > hosts.txt

# Function to remove existing network bridges
remove_bridge() {
  local bridge_name=$1
  if sudo virsh net-info ${bridge_name} >/dev/null 2>&1; then
    sudo virsh net-destroy ${bridge_name}
    sudo virsh net-undefine ${bridge_name}
  fi
}

# List of network bridges to remove
bridges=("virbr0" "br-pxe" "br-lcm" "br-others" "br-fip")

# Remove existing network bridges
for bridge in "${bridges[@]}"; do
  if [ "${bridge}" = "virbr0" ]; then
    if ip link show virbr0 >/dev/null 2>&1; then
      sudo ip link set virbr0 down
      sudo brctl delbr virbr0
    fi
  else
    remove_bridge ${bridge}
  fi
done

# Function to define and start a virtual network using virsh
define_and_start_network() {
  local bridge_name=$1
  local ip_address=$2
  local xml_file="/tmp/${bridge_name}.xml"

  sudo bash -c "cat <<EOF > ${xml_file}
<network>
  <name>${bridge_name}</name>
  <forward mode=\"nat\">
    <nat>
      <port start=\"1024\" end=\"65535\"/>
    </nat>
  </forward>
  <bridge name=\"${bridge_name}\" stp=\"on\" delay=\"0\"/>
  <ip address=\"${ip_address}\" netmask=\"255.255.255.0\"/>
</network>
EOF"
  sudo virsh net-define ${xml_file}
  sudo virsh net-start ${bridge_name}
  sudo virsh net-autostart ${bridge_name}
}

# Define and start the virtual networks
define_and_start_network "br-pxe" "192.168.122.1"
define_and_start_network "br-lcm" "192.168.123.1"
define_and_start_network "br-others" "192.168.124.1"
define_and_start_network "br-fip" "192.168.125.1"

# Check for the largest unmounted disk
LARGEST_DISK=$(lsblk -nd --output NAME,SIZE,TYPE,MOUNTPOINT | awk '$3=="disk" && $4=="" {print $1,$2}' | sort -k2 -hr | head -n 1 | awk '{print $1}')
if [ -n "$LARGEST_DISK" ]; then
  if ! lsblk -no FSTYPE /dev/$LARGEST_DISK | grep -q '.'; then
    sudo mkfs.ext4 /dev/$LARGEST_DISK
  fi
  sudo mkdir -p /var/lib/libvirt/images_new
  sudo mount /dev/$LARGEST_DISK /var/lib/libvirt/images_new
  echo "/dev/$LARGEST_DISK /var/lib/libvirt/images_new ext4 defaults 0 0" | sudo tee -a /etc/fstab
fi

# Install pip and virtualbmc
sudo python3 -m virtualenv --system-site-packages --python=python3 /opt/vbmc
sudo /opt/vbmc/bin/pip3 install wheel setuptools pkgconfig
sudo /opt/vbmc/bin/pip3 install virtualbmc

# Create the virtualbmc service
sudo bash -c 'cat <<EOF > /usr/lib/systemd/system/virtualbmc.service
[Install]
WantedBy = multi-user.target

[Service]
BlockIOAccounting = True
CPUAccounting = True
ExecReload = /bin/kill -HUP \$MAINPID
ExecStart = /opt/vbmc/bin/vbmcd --foreground
Group = root
MemoryAccounting = True
PrivateDevices = False
PrivateNetwork = False
PrivateTmp = False
PrivateUsers = False
Restart = on-failure
RestartSec = 2
Slice = vbmc.slice
TasksAccounting = True
TimeoutSec = 120
Type = simple
User = root

[Unit]
After = libvirtd.service
After = syslog.target
After = network.target
Description = vbmc service

EOF'

# Enable and start virtualbmc service
sudo systemctl daemon-reload
sudo systemctl enable virtualbmc
sudo systemctl start virtualbmc

# Check vbmc list
/opt/vbmc/bin/vbmc list

# Generate SSH key pair if it doesn't exist
if [ ! -f ~/.ssh/id_rsa ]; then
  ssh-keygen -t rsa -b 4096 -N '' -f ~/.ssh/id_rsa
fi

# Add public key to authorized_keys
cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys

echo "01-install-vbmc.sh completed successfully."
