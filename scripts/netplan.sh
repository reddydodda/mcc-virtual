# cat /etc/netplan/config.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens3:
        dhcp4: false
        dhcp6: false
  bridges:
      br0:
          addresses:
          # Please, adjust for your environment
          - 10.0.0.15/24
          dhcp4: false
          dhcp6: false
          # Please, adjust for your environment
          gateway4: 10.0.0.1
          interfaces:
          # Interface name may be different in your environment
          - ens3
          nameservers:
              addresses:
              # Please, adjust for your environment
              - 8.8.8.8
          parameters:
              forward-delay: 4
              stp: false
