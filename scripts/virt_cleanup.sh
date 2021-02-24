#!/bin/bash

l=1
m=0

for i in $(cat hosts); do

for j in kaas child ; do

for k in master worker; do

if [[ $k == worker && $j == kaas ]]; then
        break;
fi

ssh root@${i} "/opt/vbmc/bin/vbmc delete ${j}-${k}0${l}"

ssh root@${i} "virsh destroy ${j}-${k}0${l}; virsh undefine ${j}-${k}0${l}"
done
done
ssh root@${i} "/opt/vbmc/bin/vbmc delete child-ceph-${l}"
ssh root@${i} "virsh destroy child-ceph-${l}; virsh undefine child-ceph-${l}"

l=$(( l+1 ))
ssh root@${i} "/opt/vbmc/bin/vbmc list"
done
