#!/bin/bash

sudo apt update && sudo apt dist-upgrade -y

sudo apt install gcc libpq-dev python3-virtualenv libvirt-dev python3-dev python3-pip python3-venv python3-wheel -y

sudo apt install qemu-kvm libvirt-bin bridge-utils virtinst virt-manager netcat-openbsd qemu libvirt-clients libvirt-daemon-system

python3 -m virtualenv --system-site-packages --python=python3 --download /opt/vbmc

/opt/vbmc/bin/pip3 install wheel setuptools pkgconfig
/opt/vbmc/bin/pip3 install virtualbmc

cat << EOF > /etc/systemd/system/vbmcd.service
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

EOF


sudo systemctl daemon-reload
sudo systemctl enable vbmcd.service
sudo systemctl start vbmcd.service


/opt/vbmc/bin/vbmc list
