#!/bin/bash

###############
# kaas binary
###############
home_dir=$PWD

rm -rf $home_dir/kaas-bootstrap

wget https://binary.mirantis.com/releases/get_container_cloud.sh -O $home_dir/get_container_cloud.sh
chmod 0755 $home_dir/get_container_cloud.sh

cd $home_dir
./get_container_cloud.sh

cd $home_dir/kaas-bootstrap

git init
git add *
git commit -m "first commit"

mkdir $home_dir/kaas-bootstrap/templates.backup
cp -r $home_dir/kaas-bootstrap/templates/*  $home_dir/kaas-bootstrap/templates.backup/

#################
# copy licence 
#################

cp $home_dir/kaas/mirantis.lic $home_dir/kaas-bootstrap/
###################
# Update templates
###################

sed -i "s|SET_LB_HOST|${MCC_SET_LB_HOST}|g" $home_dir/kaas-bootstrap/templates/bm/cluster.yaml.template
sed -i "s|- SET_METALLB_ADDR_POOL|- ${MCC_SET_METALLB_ADDR_POOL}|g" $home_dir/kaas-bootstrap/templates/bm/cluster.yaml.template

sed -i "s|SET_LB_HOST|${MCC_SET_LB_HOST}|g" $home_dir/kaas-bootstrap/templates/bm/ipam-objects.yaml.template
sed -i "s|- SET_METALLB_ADDR_POOL|- ${MCC_SET_METALLB_ADDR_POOL}|g" $home_dir/kaas-bootstrap/templates/bm/ipam-objects.yaml.template
sed -i "s|SET_IPAM_CIDR|${SET_IPAM_CIDR}|g" $home_dir/kaas-bootstrap/templates/bm/ipam-objects.yaml.template
sed -i "s|SET_PXE_NW_GW|${SET_PXE_NW_GW}|g" $home_dir/kaas-bootstrap/templates/bm/ipam-objects.yaml.template
sed -i "s|SET_PXE_NW_DNS|${SET_PXE_NW_DNS}|g" $home_dir/kaas-bootstrap/templates/bm/ipam-objects.yaml.template
sed -i "s|SET_IPAM_POOL_RANGE|${SET_IPAM_POOL_RANGE}|g" $home_dir/kaas-bootstrap/templates/bm/ipam-objects.yaml.template

#sed -i "s|bootUEFI: true|bootUEFI: false|" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template
sed -i "s|SET_MACHINE_0_MAC|${SET_MACHINE_0_MAC}|" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template
sed -i "s|SET_MACHINE_1_MAC|${SET_MACHINE_1_MAC}|" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template
sed -i "s|SET_MACHINE_2_MAC|${SET_MACHINE_2_MAC}|" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template
sed -i "s|SET_MACHINE_0_BMC_ADDRESS|${SET_MACHINE_0_BMC_ADDRESS}|" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template
sed -i "s|SET_MACHINE_1_BMC_ADDRESS|${SET_MACHINE_1_BMC_ADDRESS}|" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template
sed -i "s|SET_MACHINE_2_BMC_ADDRESS|${SET_MACHINE_2_BMC_ADDRESS}|" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template
sed -i "s|SET_MACHINE_._IPMI_USERNAME|${USERNAME}|g" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template
sed -i "s|SET_MACHINE_._IPMI_PASSWORD|${PASSWORD}|g" $home_dir/kaas-bootstrap/templates/bm/baremetalhosts.yaml.template

#sed -i "s|name: sdc|name: vdc|" $home_dir/kaas-bootstrap/templates/bm/kaascephcluster.yaml.template


cat << EOF >> $home_dir/kaas-bootstrap/bootstrap.env

export KAAS_BM_ENABLED="true"
#
export KAAS_BM_PXE_IP="${KAAS_BM_PXE_IP}"
export KAAS_BM_PXE_MASK="${KAAS_BM_PXE_MASK}"
export KAAS_BM_PXE_BRIDGE="${KAAS_BM_PXE_BRIDGE}"
#
export KAAS_BM_BM_DHCP_RANGE="${KAAS_BM_BM_DHCP_RANGE}"
#
export KEYCLOAK_FLOATING_IP="${KEYCLOAK_FLOATING_IP}"
export IAM_FLOATING_IP="${IAM_FLOATING_IP}"
export PROXY_FLOATING_IP="${PROXY_FLOATING_IP}"
export KAAS_BOOTSTRAP_DEBUG="${KAAS_BOOTSTRAP_DEBUG}"

EOF


echo "Completed Changes"
