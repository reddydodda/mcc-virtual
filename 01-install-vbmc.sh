#!/bin/bash

# Update and upgrade OS packages
sudo apt update
sudo apt upgrade -y

# Install necessary packages
sudo apt install -y python3-virtualenv kvm virt-manager qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils ipmitool jq wget docker.io

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

# Define and start the virtual network for br-pxe using virsh
sudo bash -c 'cat <<EOF > /tmp/br-pxe.xml
<network>
  <name>br-pxe</name>
  <forward mode="nat">
    <nat>
      <port start="1024" end="65535"/>
    </nat>
  </forward>
  <bridge name="virbr-pxe" stp="on" delay="0"/>
  <ip address="192.168.122.1" netmask="255.255.255.0"/>
</network>
EOF'

sudo virsh net-define /tmp/br-pxe.xml
sudo virsh net-start br-pxe
sudo virsh net-autostart br-pxe

# Install pip and virtualbmc
sudo apt install -y python3-pip
sudo pip3 install virtualbmc

# Enable and start virtualbmc service
sudo systemctl enable virtualbmc
sudo systemctl start virtualbmc

echo "Script completed successfully."
