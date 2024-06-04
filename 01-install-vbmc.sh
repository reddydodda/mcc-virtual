#!/bin/bash

# Update and upgrade OS packages
sudo apt update
sudo apt upgrade -y

# Install necessary packages
sudo apt install gcc libpq-dev libvirt-dev python3-dev python3-pip python3-venv ipmitool jq wget \
                python3-wheel python3-virtualenv libvirt-daemon-system libvirt-clients bridge-utils docker.io \
                        qemu-kvm virtinst virt-manager netcat-openbsd qemu libvirt-clients libvirt-daemon-system -y

# Add the user to the libvirt and kvm groups
sudo usermod -aG libvirt $(whoami)
sudo usermod -aG kvm $(whoami)

# Update netplan configuration for br-lcm and br-others without DHCP
sudo bash -c 'cat <<EOF > /etc/netplan/01-netcfg.yaml
network:
  version: 2
  renderer: networkd
  bridges:
    br-lcm:
      addresses:
        - 192.168.123.1/24
      parameters:
        stp: false
        forward-delay: 0
      interfaces: []
    br-others:
      addresses:
        - 192.168.124.1/24
      parameters:
        stp: false
        forward-delay: 0
      interfaces: []
EOF'

# Apply netplan configuration
sudo netplan apply

# Check if virbr0 interface exists and remove it
if ip link show virbr0 >/dev/null 2>&1; then
    sudo ip link set virbr0 down
    sudo brctl delbr virbr0
fi
# Check if br-pxe exists and remove it
if sudo virsh net-info br-pxe >/dev/null 2>&1; then
    sudo virsh net-destroy br-pxe
    sudo virsh net-undefine br-pxe
fi

# Define and start the virtual network for br-pxe using virsh
sudo bash -c 'cat <<EOF > /tmp/br-pxe.xml
<network>
  <name>br-pxe</name>
  <forward mode="nat">
    <nat>
      <port start="1024" end="65535"/>
    </nat>
  </forward>
  <bridge name="br-pxe" stp="on" delay="0"/>
  <ip address="192.168.122.1" netmask="255.255.255.0"/>
</network>
EOF'

sudo virsh net-define /tmp/br-pxe.xml
sudo virsh net-start br-pxe
sudo virsh net-autostart br-pxe

# Install pip and virtualbmc
sudo python3 -m virtualenv --system-site-packages --python=python3 --download /opt/vbmc
sudo /opt/vbmc/bin/pip3 install wheel setuptools pkgconfig
sudo /opt/vbmc/bin/pip3 install virtualbmc

# Create the virtualbmc service
sudo bash -c 'cat <<EOF> /usr/lib/systemd/system/virtualbmc.service
[Install]
WantedBy = multi-user.target

[Service]
BlockIOAccounting = True
CPUAccounting = True
ExecReload = /bin/kill -HUP $MAINPID
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

echo "Script completed successfully."
