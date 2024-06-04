#!/bin/bash

###################
# Machine changes
###################
home_dir=$PWD

cp $home_dir/kaas-bootstrap/templates.backup/bm/baremetalhosts.yaml.template $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml

sed -i "s|SET_MACHINE_._IPMI_USERNAME|${USERNAME}|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
sed -i "s|SET_MACHINE_._IPMI_PASSWORD|${PASSWORD}|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
sed -i "s|master|${CHILD_NAMESPACE}-ceph|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
sed -i "s|metadata:|metadata:\n  namespace: ${CHILD_NAMESPACE}|g"  $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
sed -i "/provider: baremetal/a\ \ \ \ kaas.mirantis.com/region: region-one" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
sed -i "/baremetal: /a\ \ \ \ kaas.mirantis.com/region: region-one" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
sed -i "/baremetal: /a\ \ \ \ kaas.mirantis.com/provider: baremetal" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
#sed -i 's|bootUEFI: true|bootUEFI: false|' $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml

for j in {0..2}
  do
    SET_MACHINE_MAC="SET_ceph_${j}_MAC"
    SET_MACHINE_BMC_ADDRESS="SET_ceph_${j}_BMC_ADDRESS"
    sed -i "s|SET_MACHINE_${j}_MAC|${!SET_MACHINE_MAC}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
    sed -i "s|SET_MACHINE_${j}_BMC_ADDRESS|${!SET_MACHINE_BMC_ADDRESS}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/bmh-ceph.yaml
done


#################
# CLuster changes
#################

cp $home_dir/kaas-bootstrap/templates.backup/bm/kaascephcluster.yaml.template $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml
cp cephhostprofile.yaml $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/cephhostprofile.yaml

sed -i "/name: ceph/a \ \ namespace: ${CHILD_NAMESPACE}" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml
sed -i "s|ceph-mgmt|${CHILD_NAMESPACE}-ceph\n\ \ namespace: ${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml
sed -i "s|master|${CHILD_NAMESPACE}-ceph|g" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml
sed -i "s|clusterNet: 0.0.0.0/0|clusterNet: ${CEPH_CLUSTERNET_CIDR}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml
sed -i "s|publicNet: 0.0.0.0/0|publicNet: ${CEPH_PUBLICNET_CIDR}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml
sed -i "/pools:/q" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml
#sed -i "s|name: sdc|name: vdc|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml

cat << EOF >> $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/kaascephcluster.yaml
    - default: true
      deviceClass: hdd
      name: kubernetes
      replicated:
        size: 1
      role: kubernetes
    - default: false
      deviceClass: hdd
      name: volumes
      replicated:
        size: 2
      role: volumes
    - default: false
      deviceClass: hdd
      name: vms
      replicated:
        size: 2
      role: vms
    - default: false
      deviceClass: hdd
      name: backup
      replicated:
        size: 2
      role: backup
    - default: false
      deviceClass: hdd
      name: images
      replicated:
        size: 2
      role: images
    - default: false
      deviceClass: hdd
      name: other
      replicated:
        size: 2
      role: other
  k8sCluster:
    name: kaas-${CHILD_NAMESPACE}
    namespace: ${CHILD_NAMESPACE}
EOF


####################
# machine template
####################

cp $home_dir/kaas-bootstrap/templates.backup/bm/machines.yaml.template $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml

for i in {0..2}
do
 sed -i "s|name: master-${i}|name: ${CHILD_NAMESPACE}-ceph-${i}\n    namespace: ${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml
 sed -i "s|baremetal: hw-master-${i}|baremetal: hw-${CHILD_NAMESPACE}-ceph-${i}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml
done

sed -i "s|namespace: default|namespace: ${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml
sed -i "/cluster.sigs.k8s.io\/control-plane/d" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml

sed -i "/.*&cp_labels/a \ \ \ \ \ \ hostlabel.bm.kaas.mirantis.com/storage: \"true\"" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml

sed -i "s|cluster-name: kaas-mgmt|cluster-name: kaas-${CHILD_NAMESPACE}|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml
sed -i  "s|\&cp_labels|\&cp_labels\n      kaas.mirantis.com/region: region-one|" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml

cat << EOF >> /tmp/file
        bareMetalHostProfile:
          name: ceph
          namespace: ${CHILD_NAMESPACE}
EOF
sed -i "/&cp_value/r /tmp/file" $home_dir/kaas-bootstrap/${CHILD_NAMESPACE}/machines-ceph.yaml
rm /tmp/file

