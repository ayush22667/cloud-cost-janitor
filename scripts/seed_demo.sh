#!/usr/bin/env bash
# Create a small amount of real, tagged "waste" in YOUR OWN AWS account for the demo.
#   1 idle t3.micro instance, 2 unattached 10 GB gp3 volumes, 1 application load balancer with no targets,
#   plus the VPC/subnets/IGW/security group the load balancer needs (the account has no default VPC).
# Everything is tagged janitor-demo=true so the janitor's DELETE_ONLY_TAGGED guard and cleanup_demo.sh
# can find it. Idempotent: re-running reuses what already exists.
# Approx cost while running: ~$0.04/hour. Remove with scripts/cleanup_demo.sh.
set -euo pipefail

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
TAG_KEY=janitor-demo
TAG_VAL=true
PREFIX=janitor-demo
AZ_A="${REGION}a"
AZ_B="${REGION}b"
export AWS_PAGER=""

aws_() { aws --region "$REGION" --output text "$@"; }
tagspec() { echo "ResourceType=$1,Tags=[{Key=$TAG_KEY,Value=$TAG_VAL},{Key=Name,Value=$PREFIX-$2}]"; }
say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

say "Account check"
aws sts get-caller-identity --query Arn --output text | sed -E 's/[0-9]{12}/<account>/'

# --- VPC --------------------------------------------------------------------------------------
VPC=$(aws_ ec2 describe-vpcs --filters "Name=tag:Name,Values=$PREFIX-vpc" --query 'Vpcs[0].VpcId')
if [ "$VPC" = "None" ] || [ -z "$VPC" ]; then
  say "Creating VPC"
  VPC=$(aws_ ec2 create-vpc --cidr-block 10.42.0.0/16 --tag-specifications "$(tagspec vpc vpc)" --query Vpc.VpcId)
else
  say "VPC exists: $VPC"
fi

subnet() { # name cidr az
  local id
  id=$(aws_ ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" "Name=tag:Name,Values=$PREFIX-$1" --query 'Subnets[0].SubnetId')
  if [ "$id" = "None" ] || [ -z "$id" ]; then
    id=$(aws_ ec2 create-subnet --vpc-id "$VPC" --cidr-block "$2" --availability-zone "$3" --tag-specifications "$(tagspec subnet "$1")" --query Subnet.SubnetId)
  fi
  echo "$id"
}
SUBNET_A=$(subnet subnet-a 10.42.1.0/24 "$AZ_A")
SUBNET_B=$(subnet subnet-b 10.42.2.0/24 "$AZ_B")
say "Subnets: $SUBNET_A ($AZ_A), $SUBNET_B ($AZ_B)"

IGW=$(aws_ ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$VPC" --query 'InternetGateways[0].InternetGatewayId')
if [ "$IGW" = "None" ] || [ -z "$IGW" ]; then
  say "Creating internet gateway"
  IGW=$(aws_ ec2 create-internet-gateway --tag-specifications "$(tagspec internet-gateway igw)" --query InternetGateway.InternetGatewayId)
  aws_ ec2 attach-internet-gateway --internet-gateway-id "$IGW" --vpc-id "$VPC"
  RTB=$(aws_ ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" "Name=association.main,Values=true" --query 'RouteTables[0].RouteTableId')
  aws_ ec2 create-route --route-table-id "$RTB" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW" >/dev/null
fi

SG=$(aws_ ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" "Name=group-name,Values=$PREFIX-sg" --query 'SecurityGroups[0].GroupId')
if [ "$SG" = "None" ] || [ -z "$SG" ]; then
  say "Creating security group"
  SG=$(aws_ ec2 create-security-group --vpc-id "$VPC" --group-name "$PREFIX-sg" --description "janitor demo" --tag-specifications "$(tagspec security-group sg)" --query GroupId)
fi

# --- Idle instance ----------------------------------------------------------------------------
INSTANCE=$(aws_ ec2 describe-instances --filters "Name=tag:Name,Values=$PREFIX-idle" "Name=instance-state-name,Values=pending,running,stopped" --query 'Reservations[0].Instances[0].InstanceId')
if [ "$INSTANCE" = "None" ] || [ -z "$INSTANCE" ]; then
  say "Launching idle t3.micro"
  AMI=$(aws_ ssm get-parameters --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query 'Parameters[0].Value')
  INSTANCE=$(aws_ ec2 run-instances --image-id "$AMI" --instance-type t3.micro --subnet-id "$SUBNET_A" --security-group-ids "$SG" \
    --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=8,VolumeType=gp3,DeleteOnTermination=true}' \
    --tag-specifications "$(tagspec instance idle)" "$(tagspec volume idle-root)" --query 'Instances[0].InstanceId')
else
  say "Instance exists: $INSTANCE"
fi

# --- Orphaned volumes -------------------------------------------------------------------------
VOLS=()
for n in 1 2; do
  V=$(aws_ ec2 describe-volumes --filters "Name=tag:Name,Values=$PREFIX-orphan-$n" "Name=status,Values=available,creating" --query 'Volumes[0].VolumeId')
  if [ "$V" = "None" ] || [ -z "$V" ]; then
    say "Creating orphaned volume $n"
    V=$(aws_ ec2 create-volume --availability-zone "$AZ_A" --size 10 --volume-type gp3 --tag-specifications "$(tagspec volume orphan-$n)" --query VolumeId)
  fi
  VOLS+=("$V")
done

# --- Empty load balancer ----------------------------------------------------------------------
ALB=$(aws_ elbv2 describe-load-balancers --names "$PREFIX-alb" --query 'LoadBalancers[0].LoadBalancerArn' 2>/dev/null || true)
if [ -z "$ALB" ] || [ "$ALB" = "None" ]; then
  say "Creating empty application load balancer"
  ALB=$(aws_ elbv2 create-load-balancer --name "$PREFIX-alb" --type application --scheme internet-facing \
    --subnets "$SUBNET_A" "$SUBNET_B" --security-groups "$SG" \
    --tags "Key=$TAG_KEY,Value=$TAG_VAL" "Key=Name,Value=$PREFIX-alb" --query 'LoadBalancers[0].LoadBalancerArn')
else
  say "Load balancer exists"
fi

say "Seeded (region $REGION):"
printf '  instance       %s\n  volumes        %s\n  load balancer  %s\n  vpc            %s\n' "$INSTANCE" "${VOLS[*]}" "${ALB##*/loadbalancer/}" "$VPC"
echo "Give CloudWatch an hour or more to collect utilisation before the demo."
