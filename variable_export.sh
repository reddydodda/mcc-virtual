#!/bin/bash

###############
# variables
###############
export USERNAME=`echo -n "admin" | openssl base64`
export PASSWORD=`echo -n "password" | openssl base64`
export SET_IPAM_CIDR="10.10.10.0/24"
export SET_PXE_NW_GW="10.10.10.243"
export SET_PXE_NW_DNS="8.8.8.8"
export SET_IPAM_POOL_RANGE="10.10.10.171-10.10.10.199"

export MCC_SET_LB_HOST="10.10.10.4"
export MCC_SET_METALLB_ADDR_POOL="10.10.10.5-10.10.10.29"

export KAAS_BM_PXE_IP="10.10.10.1"
export KAAS_BM_PXE_MASK="24"
export KAAS_BM_PXE_BRIDGE="br0"
export KAAS_BM_BM_DHCP_RANGE="10.10.10.201,10.10.10.229"
export KEYCLOAK_FLOATING_IP="10.10.10.6"
export IAM_FLOATING_IP="10.10.10.7"
export PROXY_FLOATING_IP="10.10.10.8"
export KAAS_BOOTSTRAP_DEBUG="true"

## MCC BM
export SET_MACHINE_0_MAC="80:30:e0:24:51:d4"
export SET_MACHINE_1_MAC="1c:98:ec:1c:f5:5c"
export SET_MACHINE_2_MAC="3c:a8:2a:14:34:d0"
export SET_MACHINE_0_BMC_ADDRESS="10.10.20.201:623"
export SET_MACHINE_1_BMC_ADDRESS="10.10.20.202:623"
export SET_MACHINE_2_BMC_ADDRESS="10.10.20.203:623"

##MOSK BM

export MOSK_SET_LB_HOST="10.10.10.30"
export MOSK_SET_METALLB_ADDR_POOL="10.10.10.31-10.10.10.59"
export CHILD_NAMESPACE="mosk"
export MOSK_RELEASE="mosk-6-10-0"

export SET_master_0_MAC="20:67:7c:e1:03:98"
export SET_master_0_BMC_ADDRESS="10.10.20.207:623"
export SET_master_1_MAC="E4:43:4B:3C:B1:00"
export SET_master_1_BMC_ADDRESS="10.10.20.208:623"
export SET_master_2_MAC="E4:43:4B:3C:B4:24"
export SET_master_2_BMC_ADDRESS="10.10.20.209:623"

export SET_ctl_0_MAC="e0:07:1b:f3:7f:ec"
export SET_ctl_0_BMC_ADDRESS="10.10.20.204:623"
export SET_ctl_1_MAC="e0:07:1b:f3:9f:b4"
export SET_ctl_1_BMC_ADDRESS="10.10.20.205:623"
export SET_ctl_2_MAC="e0:07:1b:f3:fa:64"
export SET_ctl_2_BMC_ADDRESS="10.10.20.206:623"

export SET_cmp_0_MAC="48:df:37:bc:e3:60"
export SET_cmp_0_BMC_ADDRESS="10.10.20.210:623"
export SET_cmp_1_MAC="48:df:37:bc:dc:20"
export SET_cmp_1_BMC_ADDRESS="10.10.20.211:623"
export SET_cmp_2_MAC="48:df:37:b8:c8:14"
export SET_cmp_2_BMC_ADDRESS="10.10.20.212:623"


###MOSK CEPH

export SET_cmp_0_MAC="48:df:37:bc:e3:60"
export SET_cmp_0_BMC_ADDRESS="10.10.20.210:623"
export SET_cmp_1_MAC="48:df:37:bc:dc:20"
export SET_cmp_1_BMC_ADDRESS="10.10.20.211:623"
export SET_cmp_2_MAC="48:df:37:b8:c8:14"
export SET_cmp_2_BMC_ADDRESS="10.10.20.212:623"

export CEPH_CLUSTERNET_CIDR="10.10.11.0/24"
export CEPH_PUBLICNET_CIDR="10.10.10.0/24"

