#!/bin/bash

home_dir=$PWD

mkdir $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}

cp $home_dir/kaas/l2template.yaml $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/l2template.yaml
cp $home_dir/kaas/subnet.yaml $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/subnet.yaml

sed -i "s|CHILD_NAMESPACE|${CHILD_NAMESPACE}|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/l2template.yaml
sed -i "s|CHILD_NAMESPACE|${CHILD_NAMESPACE}|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/subnet.yaml


cp $home_dir/kaas-bootstrap/templates.backup/bm/baremetalhosts.yaml.template $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-master.yaml
cp $home_dir/kaas-bootstrap/templates.backup/bm/baremetalhosts.yaml.template $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ctl.yaml
cp $home_dir/kaas-bootstrap/templates.backup/bm/baremetalhosts.yaml.template $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-cmp.yaml

#sed -i '/credentialsName: master-1-bmc-secret/q' $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-cmp.yaml
for j in master ctl cmp
do
  sed -i "s|SET_MACHINE_._IPMI_USERNAME|${USERNAME}|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${j}.yaml
  sed -i "s|SET_MACHINE_._IPMI_PASSWORD|${PASSWORD}|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${j}.yaml
  sed -i "s|master|${CHILD_NAMESPACE}-${j}|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${j}.yaml
  sed -i "s|metadata:|metadata:\n  namespace: ${CHILD_NAMESPACE}|g"  $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${j}.yaml
  sed -i "/provider: baremetal/a\ \ \ \ kaas.mirantis.com/region: region-one" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${j}.yaml
  sed -i "/baremetal: /a\ \ \ \ kaas.mirantis.com/region: region-one" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${j}.yaml
  sed -i "/baremetal: /a\ \ \ \ kaas.mirantis.com/provider: baremetal" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${j}.yaml
  #sed -i 's|bootUEFI: true|bootUEFI: false|' $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${j}.yaml
done

for i in master ctl cmp
do
  for j in {0..2}
  do
    SET_MACHINE_MAC="SET_${i}_${j}_MAC"
    SET_MACHINE_BMC_ADDRESS="SET_${i}_${j}_BMC_ADDRESS"
    sed -i "s|SET_MACHINE_${j}_MAC|${!SET_MACHINE_MAC}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${i}.yaml
    sed -i "s|SET_MACHINE_${j}_BMC_ADDRESS|${!SET_MACHINE_BMC_ADDRESS}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-${i}.yaml
  done
done

####################
# 
####################

cp $home_dir/kaas-bootstrap/templates.backup/bm/cluster.yaml.template $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -ni "/kaas:/q;p" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|metadata:|metadata:\n  namespace: ${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|name: kaas-mgmt|name: kaas-${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|SET_METALLB_ADDR_POOL|${MOSK_SET_METALLB_ADDR_POOL}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|SET_LB_HOST|${MOSK_SET_LB_HOST}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|# release:|release: ${MOSK_RELEASE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|dedicatedControlPlane: false|dedicatedControlPlane: true|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|labels:|labels:\n    kaas.mirantis.com/region: region-one|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "/nodeCidr/d" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|10.233.0.0|10.233.128.0|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
sed -i "s|10.233.64.0|10.233.192.0|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
cat << EOF >> $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cluster.yaml
      kaas:
        management:
          enabled: false
      publicKeys:
      - name: bootstrap-key
      - name: cdodda
EOF

#########################
# Machine template
#########################

for j in master ctl cmp
do
  cp $home_dir/kaas-bootstrap/templates.backup/bm/machines.yaml.template $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
  for i in {0..2}
  do
    if [ ${j} == 'ctl' ] || [ ${j} == 'cmp' ]
    then
      sed -i "s|name: master-${i}|name: ${CHILD_NAMESPACE}-${j}-${i}\n    namespace: ${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
      sed -i "s|baremetal: hw-master-${i}|baremetal: hw-${CHILD_NAMESPACE}-${j}-${i}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
      sed -i "s|namespace: default|namespace: ${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
      sed -i '/cluster.sigs.k8s.io\/control-plane/d' $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
    elif [ ${j} == 'master' ]
    then
      sed -i "s|name: master-${i}|name: ${CHILD_NAMESPACE}-${j}-${i}\n    namespace: ${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
      sed -i "s|baremetal: hw-master-${i}|baremetal: hw-${CHILD_NAMESPACE}-${j}-${i}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
      sed -i "s|namespace: default|namespace: ${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
    fi
  done
  if [ ${j} == 'ctl' ]
  then
    sed -i "/.*&cp_labels/a \ \ \ \ \ \ hostlabel.bm.kaas.mirantis.com/worker: \"true\"" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
    cat << EOF >> /tmp/file
        nodeLabels:
        - key: openstack-control-plane
          value: enabled
        - key: openstack-gateway
          value: enabled
        - key: openvswitch
          value: enabled
EOF
    sed -i '/&cp_value/r /tmp/file' $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
    rm /tmp/file
  elif [ ${j} == 'cmp' ]
  then
    sed -i "/.*&cp_labels/a \ \ \ \ \ \ hostlabel.bm.kaas.mirantis.com/worker: \"true\"" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
    cat << EOF >> /tmp/file
        nodeLabels:
        - key: openstack-compute-node
          value: enabled
        - key: openvswitch
          value: enabled
EOF
    sed -i '/&cp_value/r /tmp/file' $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
    rm /tmp/file
  elif [ ${j} == 'master' ]
  then
    sed -i "/.*&cp_labels/a \ \ \ \ \ \ hostlabel.bm.kaas.mirantis.com/controlplane: \"true\"" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
  fi
  sed -i "s|cluster-name: kaas-mgmt|cluster-name: kaas-${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
  sed -i  "s|\&cp_labels|\&cp_labels\n      kaas.mirantis.com/region: region-one|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-${j}.yaml
done
cat << EOF >> /tmp/file
        bareMetalHostProfile:
          name: compute
          namespace: ${CHILD_NAMESPACE}
EOF
sed -i '/&cp_value/r /tmp/file' $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-cmp.yaml
rm /tmp/file
sed -i "/baremetal: hw-${CHILD_NAMESPACE}-worker-cmp-1/q" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-cmp.yaml

sed -i "/.*&cp_labels/a \ \ \ \ \ \ hostlabel.bm.kaas.mirantis.com/storage: \"true\"" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-cmp.yaml

