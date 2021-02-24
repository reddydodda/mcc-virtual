#!/bin/bash

l=0

echo "host_name    ipmi_ip   pxe_mac" > mcc_mac_address.txt

for i in $(cat hosts); do
m=0
for j in kaas child ; do

for k in master worker; do


if [[ $k == worker && $j == kaas ]]; then
        break;
fi

virt-install \
--connect qemu+ssh://root@${i}/system \
--virt-type=kvm \
--name=${j}-${k}0${l} \
--os-type=linux \
--os-variant=ubuntu18.04 \
--ram=49152 \
--cpu=host \
--vcpus=16 \
--disk /var/lib/libvirt/images/${j}-${k}0${l}.img,size=100,bus=virtio,format=raw \
--disk /var/lib/libvirt/images/${j}-${k}0${l}-1.img,size=100,bus=virtio,format=raw \
--disk /var/lib/libvirt/images/${j}-${k}0${l}-2.img,size=100,bus=virtio,format=raw \
--network=bridge=br0,model=virtio,mac=52:54:00:c5:91:${m}${l} \
--network=bridge=br1,model=virtio \
--graphics vnc \
--boot network,hd \
--noautoconsole

ssh root@${i} "/opt/vbmc/bin/vbmc add ${j}-${k}0${l} --username root --password admin123 --port 623${m} --address ${i}"

ssh root@${i} "/opt/vbmc/bin/vbmc start ${j}-${k}0${l}"

ipmitool -I lanplus -H ${i} -p 623${m} -U root -P admin123 chassis power status
ipmitool -I lanplus -H ${i} -p 623${m} -U root -P admin123 chassis power off

echo "${j}-${k}0${l} ${i}:623${m} 52:54:00:c5:91:${m}${l}"

m=$(( m+1 ))

#mac_address=$(ssh root@${i} "virsh dumpxml ${j}-${k}0${l} | grep 'mac address' | awk -F\' 'NR==1{ print $2}'" 2>&1)

done
done
l=$(( l+1 ))
ssh root@${i} "/opt/vbmc/bin/vbmc list"
done
