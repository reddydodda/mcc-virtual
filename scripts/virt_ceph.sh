#!/bin/bash

l=0

echo "host_name    ipmi_ip   pxe_mac" > mac_address.txt

for i in $(cat hosts); do

virt-install \
--connect qemu+ssh://root@${i}/system \
--virt-type=kvm \
--name=child-ceph-${l} \
--os-type=linux \
--os-variant=ubuntu18.04 \
--ram=49152 \
--cpu=host \
--vcpus=16 \
--disk /var/lib/libvirt/images/child-ceph-${l}.img,size=100,bus=virtio,format=raw \
--disk /var/lib/libvirt/images/child-ceph-${l}-1.img,size=100,bus=virtio,format=raw \
--disk /var/lib/libvirt/images/child-ceph-${l}-2.img,size=100,bus=virtio,format=raw \
--disk /var/lib/libvirt/images/child-ceph-${l}-3.img,size=100,bus=virtio,format=raw \
--disk /var/lib/libvirt/images/child-ceph-${l}-4.img,size=100,bus=virtio,format=raw \
--network=bridge=br0,model=virtio,mac=52:54:00:c5:91:b${l} \
--network=bridge=br1,model=virtio \
--graphics vnc \
--boot network,hd \
--noautoconsole

ssh root@${i} "/opt/vbmc/bin/vbmc add child-ceph-${l} --username root --password admin123 --port 624${l} --address ${i}"

ssh root@${i} "/opt/vbmc/bin/vbmc start child-ceph-${l}"

ipmitool -I lanplus -H ${i} -p 624${l} -U root -P admin123 chassis power status
ipmitool -I lanplus -H ${i} -p 624${l} -U root -P admin123 chassis power off

#mac_address=$(ssh root@${i} "virsh dumpxml child-ceph-${l} | grep 'mac address' | awk -F\' 'NR==1{ print $2}'" 2>&1)
echo "child-ceph-${l} {i}:624${l} 52:54:00:c5:91:b${l}" >> mac_address.txt
l=$(( l+1 ))
ssh root@${i} "/opt/vbmc/bin/vbmc list"
done
