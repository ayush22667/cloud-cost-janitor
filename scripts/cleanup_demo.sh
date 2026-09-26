#!/usr/bin/env bash
# Remove everything scripts/seed_demo.sh created (tag janitor-demo=true), in dependency order:
#   instances -> load balancer -> volumes -> [snapshots the janitor made] -> security group -> IGW -> subnets -> VPC
# Idempotent: skips what is already gone. Pass --snapshots to also delete pre-delete snapshots the janitor created.
set -euo pipefail

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
TAG_KEY=janitor-demo
TAG_VAL=true
PREFIX=janitor-demo
export AWS_PAGER=""
DELETE_SNAPSHOTS=false
[ "${1:-}" = "--snapshots" ] && DELETE_SNAPSHOTS=true

aws_() { aws --region "$REGION" --output text "$@"; }
say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
TAGF="Name=tag:$TAG_KEY,Values=$TAG_VAL"

say "Instances"
IDS=$(aws_ ec2 describe-instances --filters "$TAGF" "Name=instance-state-name,Values=pending,running,stopping,stopped" --query 'Reservations[].Instances[].InstanceId')
if [ -n "$IDS" ]; then
  aws_ ec2 terminate-instances --instance-ids $IDS >/dev/null
  aws --region "$REGION" ec2 wait instance-terminated --instance-ids $IDS
  echo "  terminated: $IDS"
fi

say "Load balancer"
ALB=$(aws_ elbv2 describe-load-balancers --names "$PREFIX-alb" --query 'LoadBalancers[0].LoadBalancerArn' 2>/dev/null || true)
if [ -n "$ALB" ] && [ "$ALB" != "None" ]; then
  aws_ elbv2 delete-load-balancer --load-balancer-arn "$ALB"
  aws --region "$REGION" elbv2 wait load-balancers-deleted --load-balancer-arns "$ALB"
  echo "  deleted: ${ALB##*/loadbalancer/}"
fi

say "Volumes"
VOLS=$(aws_ ec2 describe-volumes --filters "$TAGF" "Name=status,Values=available" --query 'Volumes[].VolumeId')
for v in $VOLS; do aws_ ec2 delete-volume --volume-id "$v"; echo "  deleted: $v"; done

if $DELETE_SNAPSHOTS; then
  say "Snapshots created by the janitor"
  SNAPS=$(aws_ ec2 describe-snapshots --owner-ids self --filters "Name=tag-key,Values=janitor:plan-id" --query 'Snapshots[].SnapshotId')
  for s in $SNAPS; do aws_ ec2 delete-snapshot --snapshot-id "$s"; echo "  deleted: $s"; done
fi

say "Network"
VPC=$(aws_ ec2 describe-vpcs --filters "Name=tag:Name,Values=$PREFIX-vpc" --query 'Vpcs[0].VpcId')
if [ -n "$VPC" ] && [ "$VPC" != "None" ]; then
  # The ALB's network interfaces can linger for a minute after deletion; wait for the SG to be free.
  SG=$(aws_ ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" "Name=group-name,Values=$PREFIX-sg" --query 'SecurityGroups[0].GroupId')
  if [ -n "$SG" ] && [ "$SG" != "None" ]; then
    for _ in $(seq 1 30); do
      ENIS=$(aws_ ec2 describe-network-interfaces --filters "Name=group-id,Values=$SG" --query 'NetworkInterfaces[].NetworkInterfaceId')
      [ -z "$ENIS" ] && break
      sleep 5
    done
    aws_ ec2 delete-security-group --group-id "$SG"; echo "  deleted sg: $SG"
  fi
  IGW=$(aws_ ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$VPC" --query 'InternetGateways[0].InternetGatewayId')
  if [ -n "$IGW" ] && [ "$IGW" != "None" ]; then
    aws_ ec2 detach-internet-gateway --internet-gateway-id "$IGW" --vpc-id "$VPC"
    aws_ ec2 delete-internet-gateway --internet-gateway-id "$IGW"; echo "  deleted igw: $IGW"
  fi
  for s in $(aws_ ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" --query 'Subnets[].SubnetId'); do
    aws_ ec2 delete-subnet --subnet-id "$s"; echo "  deleted subnet: $s"
  done
  aws_ ec2 delete-vpc --vpc-id "$VPC"; echo "  deleted vpc: $VPC"
fi
say "Done"
