#!/usr/bin/env python

import argparse

from troposphere import Template, Parameter, Output, Tag, Ref, GetAZs, GetAtt
from troposphere import Sub, Select, Base64, Join, FindInMap
from troposphere import AWSHelperFn, If, Not, Equals
from troposphere import NoValue, AccountId, StackName, Region

import troposphere.ec2 as ec2
import troposphere.logs as logs
import troposphere.autoscaling as autoscaling
import troposphere.elasticloadbalancingv2 as loadbalancing
import troposphere.ecs as ecs
import troposphere.iam as iam
import troposphere.policies as policies
import troposphere.applicationautoscaling as applicationautoscaling
import troposphere.cloudwatch as cloudwatch
import troposphere.cloudfront as cloudfront

import awacs.aws as aws
import awacs.sts as actions_sts
import awacs.s3 as actions_s3
import awacs.cloudformation as actions_cloudformation
import awacs.logs as actions_logs
import awacs.cloudwatch as actions_cloudwatch
import awacs.secretsmanager as actions_secretsmanager
import awacs.ssm as actions_ssm
import awacs.kms as actions_kms

cli_parser = argparse.ArgumentParser(description="imgproxy CloudFormation template generator")
cli_parser.add_argument("-f", "--format",
                        choices=["yaml", "json"],
                        default="yaml",
                        help="Output format. Default: yaml")
cli_parser.add_argument("-o", "--output",
                        type=str,
                        help="Output file name. When not set, the template will be printed to stdout")
cli_parser.add_argument("-t", "--launch-type",
                        choices=["FARGATE", "EC2"],
                        default="FARGATE",
                        help="ESC Launch type. Default: FARGATE")
cli_parser.add_argument("-s", "--subnets-number",
                        type=int,
                        default=3,
                        help="Number of subnets to create. Default: 3")
cli_parser.add_argument("-N", "--no-network",
                        action="store_true",
                        help="Don't create network resources (VPC, subnets, load balancer, etc)")
cli_parser.add_argument("-C", "--no-cluster",
                        action="store_true",
                        help="Don't create ECS cluster")

args = cli_parser.parse_args()

if args.no_cluster and not args.no_network:
  cli_parser.error("--no-cluster can be used only with --no-network")

template = Template()
template.set_version("2010-09-09")
template.set_description("imgproxy running in ECS")

yes_no = ["Yes", "No"]
def IfYes(param): return Equals(Ref(param), "Yes")

class Contains(AWSHelperFn):
    def __init__(self, value_one: object, value_two: object) -> None:
        self.data = {"Fn::Contains": [value_one, value_two]}

arm64_instance_types = [
  "c7g.medium",
  "c7g.large",
  "c7g.xlarge",
  "c7g.2xlarge",
  "c7g.4xlarge",
  "c7g.8xlarge",
  "c7g.12xlarge",
  "c7g.16xlarge",
  "t4g.small",
  "t4g.medium",
  "t4g.large",
  "t4g.xlarge",
  "t4g.2xlarge",
]

amd64_instance_types = [
  "c7i.large",
  "c7i.xlarge",
  "c7i.2xlarge",
  "c7i.4xlarge",
  "c7i.8xlarge",
  "c7i.12xlarge",
  "c7i.16xlarge",
  "c7a.large",
  "c7a.xlarge",
  "c7a.2xlarge",
  "c7a.4xlarge",
  "c7a.8xlarge",
  "c7a.12xlarge",
  "c7a.16xlarge",
  "c6i.large",
  "c6i.xlarge",
  "c6i.2xlarge",
  "c6i.4xlarge",
  "c6i.8xlarge",
  "c6i.12xlarge",
  "c6i.16xlarge",
  "c6a.large",
  "c6a.xlarge",
  "c6a.2xlarge",
  "c6a.4xlarge",
  "c6a.8xlarge",
  "c6a.12xlarge",
  "c6a.16xlarge",
  "t3.small",
  "t3.medium",
  "t3.large",
  "t3.xlarge",
  "t3.2xlarge",
]

# ==============================================================================
# PARAMETERS
# ==============================================================================

network_params_group = "Network"
cluster_params_group = "Cluster"
service_params_group = "Service"
environment_secret_params_group = "Load environment from an AWS Secrets Manager secret"
environment_systems_manager_params_group = "Load environment from AWS Systems Manager Parameter Store"
s3_params_group = "S3 integration"
endpoint_params_group = "Endpoint"

# Network ----------------------------------------------------------------------

if args.no_network:
  vpc = template.add_parameter(Parameter(
    "VpcId",
    Type="AWS::EC2::VPC::Id",
    Description="ID of VPC to deploy imgproxy into",
  ))
  template.add_parameter_to_group(vpc, network_params_group)
  template.set_parameter_label(vpc, "VPC ID")

  if not args.no_cluster or args.launch_type == "FARGATE":
    subnets = template.add_parameter(Parameter(
      "SubnetIds",
      Type="List<AWS::EC2::Subnet::Id>",
      Description="IDs of Subnets to deploy imgproxy into",
    ))
    template.add_parameter_to_group(subnets, network_params_group)
    template.set_parameter_label(subnets, "Subnet IDs")

    ecs_host_security_group = template.add_parameter(Parameter(
      "ECSHostSecurityGroupId",
      Type="AWS::EC2::SecurityGroup::Id",
      Description="ID of security group to use for ECS hosts. Should allow access from the load balancer",
    ))
    template.add_parameter_to_group(ecs_host_security_group, network_params_group)
    template.set_parameter_label(ecs_host_security_group, "ECS host security group ID")

  load_balancer_listener = template.add_parameter(Parameter(
    "LoadBalancerListenerArn",
    Type="String",
    Description="ARN of the load balancer listener to use for imgproxy",
    AllowedPattern="arn:aws:elasticloadbalancing:[a-z0-9-]+:[0-9]+:listener/app/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9]+",
    ConstraintDescription="Must be a valid load balancer listener ARN",
  ))
  template.add_parameter_to_group(load_balancer_listener, network_params_group)
  template.set_parameter_label(load_balancer_listener, "Load balancer listener ARN")

# Cluster ----------------------------------------------------------------------

if args.launch_type == "EC2" and not args.no_cluster:
  cluster_instance_type = template.add_parameter(Parameter(
    "ClusterInstanceType",
    Type="String",
    Description="EC2 instance type to use in your ECS cluster",
    Default="c7g.medium",
    AllowedValues=arm64_instance_types + amd64_instance_types,
  ))
  template.add_parameter_to_group(cluster_instance_type, cluster_params_group)
  template.set_parameter_label(cluster_instance_type, "EC2 instance type")

  cluster_deised_size = template.add_parameter(Parameter(
    "ClusterDeisedSize",
    Type="Number",
    Description="Number of EC2 instances to initially launch in your ECS cluster",
    Default=2,
    MinValue=1,
  ))
  template.add_parameter_to_group(cluster_deised_size, cluster_params_group)
  template.set_parameter_label(cluster_deised_size, "Desired number of instances")

  cluster_min_size = template.add_parameter(Parameter(
    "ClusterMinSize",
    Type="Number",
    Description="The minimum number of EC2 instances to launch in your ECS cluster",
    Default=1,
    MinValue=1,
  ))
  template.add_parameter_to_group(cluster_min_size, cluster_params_group)
  template.set_parameter_label(cluster_min_size, "Minimum number of instances")

  cluster_max_size = template.add_parameter(Parameter(
    "ClusterMaxSize",
    Type="Number",
    Description="The maximum number of EC2 instances to launch in your ECS cluster",
    Default=5,
    MinValue=1,
  ))
  template.add_parameter_to_group(cluster_max_size, cluster_params_group)
  template.set_parameter_label(cluster_max_size, "Maximum number of instances")

  cluster_target_capacity_utilization = template.add_parameter(Parameter(
    "ClusterTargetCapacityUtilization",
    Type="Number",
    Description="""
The target capacity utilization as a percentage for the EC2 Auto Scaling group.
For example, if you want the Auto Scaling group to maintain 10% spare capacity, then that means the
utilization is 90%, so use a value of 90.
The value of 100 percent results in the Amazon EC2 instances in your Auto Scaling group being
completely used
    """.strip().replace("\n", " "),
    Default=100,
    MinValue=1,
    MaxValue=100,
  ))
  template.add_parameter_to_group(cluster_target_capacity_utilization, cluster_params_group)
  template.set_parameter_label(cluster_target_capacity_utilization, "Target capacity utilization")

  cluster_on_demand_percentage = template.add_parameter(Parameter(
    "ClusterOnDemandPercentage",
    Type="Number",
    Description="""
Controls the percentages of On-Demand Instances and Spot Instances in the EC2 Auto Scaling group.
If set to 100, only On-Demand Instances are used
    """.strip().replace("\n", " "),
    Default=100,
    MinValue=1,
    MaxValue=100,
  ))
  template.add_parameter_to_group(cluster_on_demand_percentage, cluster_params_group)
  template.set_parameter_label(cluster_on_demand_percentage, "On-Demand instances percentage")

  cluster_add_warm_pool = template.add_parameter(Parameter(
    "ClusterAddWramPool",
    Type="String",
    Description="""
Create a pool of pre-initialized EC2 instances that sits alongside the EC2 Auto Scaling group.
Whenever your application needs to scale out, the Auto Scaling group can draw on the warm pool
to meet its new desired capacity.
Can not be used if ClusterOnDemandPercentage is below 100
    """.strip().replace("\n", " "),
    Default="Yes",
    AllowedValues=yes_no,
  ))
  template.add_parameter_to_group(cluster_add_warm_pool, cluster_params_group)
  template.set_parameter_label(cluster_add_warm_pool, "Add warm pool")

# Service ----------------------------------------------------------------------

if args.no_cluster:
  ecs_cluster = template.add_parameter(Parameter(
    "ClusterName",
    Type="String",
    Description="Name (not ARN!) of ECS cluster to deploy imgproxy into",
    AllowedPattern="[a-zA-Z0-9-_]+",
    ConstraintDescription="Must be a valid ECS cluster name",
  ))
  template.add_parameter_to_group(ecs_cluster, service_params_group)
  template.set_parameter_label(ecs_cluster, "ECS cluster name")

cpu_arch = template.add_parameter(Parameter(
  "CpuArchitecture",
  Type="String",
  Description="CPU architecture of the Docker image. ARM64 is highly recommended",
  Default="ARM64",
  AllowedValues=[
    "ARM64",
    "AMD64"
  ],
))
template.add_parameter_to_group(cpu_arch, service_params_group)
template.set_parameter_label(cpu_arch, "CPU architecture")

docker_image = template.add_parameter(Parameter(
  "DockerImage",
  Type="String",
  Description="""
The imgproxy or imgproxy Pro Docker image name stored in a public registry or your ECR registry
  """.strip().replace("\n", " "),
  Default="darthsim/imgproxy:v3",
))
template.add_parameter_to_group(docker_image, service_params_group)
template.set_parameter_label(docker_image, "Docker image")

container_cpu = template.add_parameter(Parameter(
  "ContainerCpu",
  Type="Number",
  Description="Amount of CPU to give to the container. 1024 is 1 CPU",
  Default=1024,
  MinValue=1024,
))
template.add_parameter_to_group(container_cpu, service_params_group)
template.set_parameter_label(container_cpu, "CPU per task")

container_memory = template.add_parameter(Parameter(
  "ContainerMemory",
  Type="Number",
  Description="Amount of memory in megabytes to give to the container",
  Default=2048 if args.launch_type == "FARGATE" else 1536,
  MinValue=2048 if args.launch_type == "FARGATE" else 512,
))
template.add_parameter_to_group(container_memory, service_params_group)
template.set_parameter_label(container_memory, "Memory per task")

task_desired_count = template.add_parameter(Parameter(
  "TaskDesiredCount",
  Type="Number",
  Description="Number of imgproxy instances to initially launch in your service",
  Default=2,
  MinValue=1,
))
template.add_parameter_to_group(task_desired_count, service_params_group)
template.set_parameter_label(task_desired_count, "Desired number of tasks")

task_min_count = template.add_parameter(Parameter(
  "TaskMinCount",
  Type="Number",
  Description="Mainimum number of imgproxy instances we can launch in your service",
  Default=2,
))
template.add_parameter_to_group(task_min_count, service_params_group)
template.set_parameter_label(task_min_count, "Minimum number of tasks")

task_max_count = template.add_parameter(Parameter(
  "TaskMaxCount",
  Type="Number",
  Description="Maximum number of imgproxy instances we can launch in your service",
  Default=8,
))
template.add_parameter_to_group(task_max_count, service_params_group)
template.set_parameter_label(task_max_count, "Maximum number of tasks")

# Secret manager ---------------------------------------------------------------

environment_secret_arn = template.add_parameter(Parameter(
  "EnvironmentSecretARN",
  Type="String",
  Description="""
ARN of an AWS Secrets Manager secret containing environment variables.
See https://docs.imgproxy.net/latest/configuration/loading_environment_variables#environment-file-syntax
for the secret syntax.
See https://docs.imgproxy.net/configuration for supported environment variables
  """.strip().replace("\n", " "),
  Default="",
))
template.add_parameter_to_group(environment_secret_arn, environment_secret_params_group)
template.set_parameter_label(environment_secret_arn, "Secrets Manager secret ARN (optional)")

environment_secret_version_id = template.add_parameter(Parameter(
  "EnvironmentSecretVersionID",
  Type="String",
  Description="""
Version ID of the AWS Secrets Manager secret containing environment variables.
If not set, the latest version is used
  """.strip().replace("\n", " "),
  Default="",
))
template.add_parameter_to_group(environment_secret_version_id, environment_secret_params_group)
template.set_parameter_label(environment_secret_version_id, "Secrets Manager secret version ID (optional)")

# Systems manager --------------------------------------------------------------

environment_systems_manager_parameters_path = template.add_parameter(Parameter(
  "EnvironmentSystemsManagerParametersPath",
  Type="String",
  Description="""
A path of AWS Systems Manager Parameter Store parameters containing the environment variables.
The path should start with a slash (/) but should not have a slash (/) at the end.
See https://docs.imgproxy.net/latest/configuration/loading_environment_variables#aws-systems-manager-path
to learn how imgproxy maps AWS Systems Manager Parameter Store parameters to environment variables.
See https://docs.imgproxy.net/configuration for supported environment variables
  """.strip().replace("\n", " "),
  Default="",
))
template.add_parameter_to_group(environment_systems_manager_parameters_path, environment_systems_manager_params_group)
template.set_parameter_label(environment_systems_manager_parameters_path, "Systems Manager Parameter Store parameters path (optional)")

# S3 ---------------------------------------------------------------------------

s3_objects = template.add_parameter(Parameter(
  "S3Objects",
  Type="CommaDelimitedList",
  Description="""
ARNs of S3 objects (comma delimited) that imgproxy should have access to.
You can grant access to multiple objects with a single ARN by using wildcards.
Example: arn:aws:s3:::my-images-bucket/*,arn:aws:s3:::my-assets-bucket/images/*
  """.strip().replace("\n", " "),
  Default="",
))
template.add_parameter_to_group(s3_objects, s3_params_group)
template.set_parameter_label(s3_objects, "S3 objects (optional)")

s3_assume_role_arn = template.add_parameter(Parameter(
  "S3AssumeRoleARN",
  Type="String",
  Description="""
ARN of IAM Role that S3 client should assume. This allows you to provide imgproxy access to
third-party S3 buckets that the assummed IAM Role has access to
  """.strip().replace("\n", " "),
  Default="",
))
template.add_parameter_to_group(s3_assume_role_arn, s3_params_group)
template.set_parameter_label(s3_assume_role_arn, "IAM Role ARN to assume (optional)")

s3_multi_region = template.add_parameter(Parameter(
  "S3MultiRegion",
  Type="String",
  Description="""
Should imgproxy be able to access S3 buckets in other regions?
By default, imgproxy can access only S3 buckets locates in the same region as imgproxy
  """.strip().replace("\n", " "),
  Default="No",
  AllowedValues=yes_no,
))
template.add_parameter_to_group(s3_multi_region, s3_params_group)
template.set_parameter_label(s3_multi_region, "Enable multi-region mode")

s3_client_side_decryption = template.add_parameter(Parameter(
  "S3ClientSideDecryption",
  Type="String",
  Description="""
Should imgproxy use S3 decryption client?
The decription client will be used for all objects in all S3 buckets, so unecrypted objects won't
be accessable
  """.strip().replace("\n", " "),
  Default="No",
  AllowedValues=yes_no,
))
template.add_parameter_to_group(s3_client_side_decryption, s3_params_group)
template.set_parameter_label(s3_client_side_decryption, "Enable client-side decryption")

# Endpoint ---------------------------------------------------------------------

path_prefix = template.add_parameter(Parameter(
  "PathPrefix",
  Type="String",
  Description="Path prefix, beginning with a slash (/). Do not add a slash (/) at the end of the path",
  Default="",
))
template.add_parameter_to_group(path_prefix, endpoint_params_group)
template.set_parameter_label(path_prefix, "Path prefix (optional)")

if not args.no_network:
  create_cloudfront_distribution = template.add_parameter(Parameter(
    "CreateCloudFrontDistribution",
    Type="String",
    Description="""
  Should caching CloudFront distribution be created?
  This CloudFront distribution will automatically add the path prefix when requesting the origin.
  Also, it will automatically add X-Imgproxy-Auth header with the provided authorization token
    """.strip().replace("\n", " "),
    Default="Yes",
    AllowedValues=yes_no,
  ))
  template.add_parameter_to_group(create_cloudfront_distribution, endpoint_params_group)
  template.set_parameter_label(create_cloudfront_distribution, "Create CloudForont distribution?")

authorization_token = template.add_parameter(Parameter(
  "AuthorizationToken",
  Type="String",
  Description="""
The authorization token token that should be provided via the X-Imgproxy-Auth header to get access
to imgproxy.
Allows to prevent access to imgproxy bypassing CDN.
The X-Imgproxy-Auth header will be checked by the load balancer listener rule
  """.strip().replace("\n", " "),
  Default="",
))
template.add_parameter_to_group(authorization_token, endpoint_params_group)
template.set_parameter_label(authorization_token, "Authorization token (optional)")

# ==============================================================================
# CONDITIONS
# ==============================================================================

if args.launch_type == "EC2" and not args.no_cluster:
  cluster_use_spot = template.add_condition(
    "ClusterOnDemandOnly",
    Not(Equals(Ref(cluster_on_demand_percentage), 100)),
  )

  cluster_should_add_warm_pool = template.add_condition(
    "ClusterShouldAddWramPool",
    IfYes(cluster_add_warm_pool),
  )

have_environment_secret_arn = template.add_condition(
  "HaveEnvironmentSecretArn",
  Not(Equals(Ref(environment_secret_arn), "")),
)

have_environment_systems_manager_parameters_path = template.add_condition(
  "HaveEnvironmentSystemsManagerParametersPath",
  Not(Equals(Ref(environment_systems_manager_parameters_path), "")),
)

have_s3_objects = template.add_condition(
  "HaveS3Objects",
  Not(Equals(Join("", Ref(s3_objects)), "")),
)

have_s3_assume_role_arn = template.add_condition(
  "HaveS3AssumeRole",
  Not(Equals(Ref(s3_assume_role_arn), "")),
)

enable_s3_multi_region = template.add_condition(
  "EnableS3MultiRegion",
  IfYes(s3_multi_region),
)

enable_s3_client_side_decryption = template.add_condition(
  "EnableS3ClientSideDecryption",
  IfYes(s3_client_side_decryption),
)

have_path_prefix = template.add_condition(
  "HavePathPrefix",
  Not(Equals(Ref(path_prefix), "")),
)

if not args.no_network:
  deploy_cloudfront = template.add_condition(
    "DeployCloudFront",
    IfYes(create_cloudfront_distribution),
  )

have_authorization_token = template.add_condition(
  "HaveAuthorizationToken",
  Not(Equals(Ref(authorization_token), "")),
)

# ==============================================================================
# RULES
# ==============================================================================

if args.launch_type == "EC2" and not args.no_cluster:
  template.add_rule(
    "testWarmPoolAndNoSpot",
    {
      "RuleCondition": Not(Equals(Ref(cluster_on_demand_percentage), "100")),
      "Assertions": [
          {
              "Assert": Not(IfYes(cluster_add_warm_pool)),
              "AssertDescription": "Can't use a warm pool if ClusterOnDemandPercentage is below 100"
          }
      ]
    }
  )

  template.add_rule(
    "testArm64InstanceType",
    {
      "RuleCondition": Equals(Ref(cpu_arch), "ARM64"),
      "Assertions": [
          {
              "Assert": Contains(arm64_instance_types, Ref(cluster_instance_type)),
              "AssertDescription": "ARM64 service requires ARM64-compatible instance type"
          }
      ]
    }
  )

  template.add_rule(
    "testAmd64InstanceType",
    {
      "RuleCondition": Equals(Ref(cpu_arch), "AMD64"),
      "Assertions": [
          {
              "Assert": Contains(amd64_instance_types, Ref(cluster_instance_type)),
              "AssertDescription": "AMD64 service requires AMD64-compatible instance type"
          }
      ]
    }
  )

# ==============================================================================
# MAPPINGS
# ==============================================================================

template.add_mapping("Architectures", {
  "ARM64": {
    "Arch": "ARM64",
    "ImageId": "{{resolve:ssm:/aws/service/bottlerocket/aws-ecs-1/arm64/latest/image_id}}",
  },
  "AMD64": {
    "Arch": "X86_64",
    "ImageId": "{{resolve:ssm:/aws/service/bottlerocket/aws-ecs-1/x86_64/latest/image_id}}",
  },
})

# ==============================================================================
# CLOUDWATCH LOGS
# ==============================================================================

log_group = template.add_resource(logs.LogGroup(
  "CloudWatchLogGroup",
  LogGroupName=StackName,
  RetentionInDays=365,
))

# ==============================================================================
# NETWORK
# ==============================================================================

if not args.no_network:
  vpc = template.add_resource(ec2.VPC(
    "VPC",
    EnableDnsSupport=True,
    EnableDnsHostnames=True,
    CidrBlock="10.0.0.0/16",
    Tags= [
      Tag("Name", Join("-", [StackName, "VPC"])),
    ],
  ))

  internet_gateway = template.add_resource(ec2.InternetGateway(
    "InternetGateway",
    Tags= [
      Tag("Name", Join("-", [StackName, "Internet-Gateway"])),
    ],
  ))

  gateway_attachement = template.add_resource(ec2.VPCGatewayAttachment(
    "GatewayAttachement",
    VpcId=Ref(vpc),
    InternetGatewayId=Ref(internet_gateway),
  ))

  route_table = template.add_resource(ec2.RouteTable(
    "PublicRouteTable",
    VpcId=Ref(vpc),
    Tags= [
      Tag("Name", Join("-", [StackName, "Routes"])),
    ],
  ))

  template.add_resource(ec2.Route(
    "PublicRoute",
    DependsOn=gateway_attachement,
    RouteTableId=Ref(route_table),
    DestinationCidrBlock="0.0.0.0/0",
    GatewayId=Ref(internet_gateway),
  ))

  subnet_refs = []

  for n in range(args.subnets_number):
    subnet = template.add_resource(ec2.Subnet(
      "PublicSubnet{0}".format(n),
      AvailabilityZone=Select(n, GetAZs()),
      VpcId=Ref(vpc),
      CidrBlock="10.0.{0}.0/20".format(n * 16),
      MapPublicIpOnLaunch=True,
      Tags=[
        Tag("Name", Join("-", [StackName, "Subnet", str(n)]))
      ],
    ))

    template.add_resource(ec2.SubnetRouteTableAssociation(
      "PublicSubnet{0}RouteTableAssociation".format(n),
      SubnetId=Ref(subnet),
      RouteTableId=Ref(route_table),
    ))

    subnet_refs.append(Ref(subnet))

  # This security group defines who/where is allowed to access the Application Load Balancer.
  # By default, we've opened this up to the public internet (0.0.0.0/0) but can you restrict
  # it further if you want.
  load_balancer_security_group = template.add_resource(ec2.SecurityGroup(
    "LoadBalancerSecurityGroup",
    VpcId=Ref(vpc),
    GroupDescription="Access to the load balancer that sits in front of ECS",
    SecurityGroupIngress=[
      # Allow access from anywhere to our ECS services
      { "CidrIp": "0.0.0.0/0", "IpProtocol": -1 },
    ],
    Tags= [
      Tag("Name", Join("-", [StackName, "SG-LoadBalancers"])),
    ],
  ))

  # This security group defines who/where is allowed to access the ECS hosts directly.
  # By default we're just allowing access from the load balancer. If you want to SSH
  # into the hosts, or expose non-load balanced services you can open their ports here.
  ecs_host_security_group = template.add_resource(ec2.SecurityGroup(
    "ECSHostSecurityGroup",
    VpcId=Ref(vpc),
    GroupDescription="Access to the ECS hosts and the tasks/containers that run on them",
    SecurityGroupIngress=[
      # Only allow inbound access to ECS from the ELB
      { "SourceSecurityGroupId": Ref(load_balancer_security_group), "IpProtocol": -1 },
    ],
    Tags= [
      Tag("Name", Join("-", [StackName, "SG-ECS-Hosts"])),
    ],
  ))

elif not args.no_cluster or args.launch_type == "FARGATE":
  subnet_refs = Ref(subnets)

# ==============================================================================
# ECS CLUSTER
# ==============================================================================

if not args.no_cluster:
  ecs_cluster = template.add_resource(ecs.Cluster(
    "ECSCluster",
    ClusterName=Join("-", [StackName, "Cluster"]),
  ))

# ==============================================================================
# ECS CAPACITY PROVIDER
# ==============================================================================

ecs_capacity_provider_associations = None

if not args.no_cluster:
  if args.launch_type == "EC2":
    ec2_instance_role = template.add_resource(iam.Role(
      "EC2InstanceRole",
      RoleName=Join("-", [StackName, "ec2-instance"]),
      Path="/",
      AssumeRolePolicyDocument=aws.PolicyDocument(
        Version="2012-10-17",
        Statement=[aws.Statement(
          Effect=aws.Allow,
          Action=[actions_sts.AssumeRole],
          Principal=aws.Principal("Service", ["ec2.amazonaws.com"]),
        )],
      ),
      ManagedPolicyArns=[
        "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role",
      ],
      Policies=[iam.Policy(
        PolicyName="cloudformation-signal",
        PolicyDocument=aws.PolicyDocument(
          Version="2012-10-17",
          Statement=[aws.Statement(
            Effect=aws.Allow,
            Action=[
              actions_cloudformation.DescribeStackResource,
              actions_cloudformation.SignalResource,
            ],
            Resource=[Join("", ["arn:aws:cloudformation:", Region, ":", AccountId, ":stack/", StackName, "/*"])],
          )],
        ),
      )],
    ))

    ec2_instance_profile = template.add_resource(iam.InstanceProfile(
      "EC2InstanceProfile",
      Path="/",
      Roles=[Ref(ec2_instance_role)],
    ))

    ec2_autoscaling_group_title = "EC2AutoScalingGroup"

    ec2_launch_template = template.add_resource(ec2.LaunchTemplate(
      "EC2LaunchTemplate",
      LaunchTemplateName=Join("-", [StackName, "Launch-Template"]),
      LaunchTemplateData=ec2.LaunchTemplateData(
        ImageId=FindInMap("Architectures", Ref(cpu_arch), "ImageId"),
        SecurityGroupIds=[Ref(ecs_host_security_group)],
        InstanceType=Ref(cluster_instance_type),
        IamInstanceProfile=ec2.IamInstanceProfile(Name=Ref(ec2_instance_profile)),
        UserData=Base64(Sub("""
[settings.ecs]
cluster = "${{{cluster}}}"

[settings.cloudformation]
should-signal = true
stack-name = "${{AWS::StackName}}"
logical-resource-id = "{autoscaling_group}"
        """.strip().format(cluster=ecs_cluster.title, autoscaling_group=ec2_autoscaling_group_title))),
      ),
    ))

    ec2_autoscaling_group = template.add_resource(autoscaling.AutoScalingGroup(
      ec2_autoscaling_group_title,
      VPCZoneIdentifier=subnet_refs,
      MixedInstancesPolicy=If(
        cluster_use_spot,
        autoscaling.MixedInstancesPolicy(
          LaunchTemplate=autoscaling.LaunchTemplate(
            LaunchTemplateSpecification=autoscaling.LaunchTemplateSpecification(
              LaunchTemplateId=Ref(ec2_launch_template),
              Version=GetAtt(ec2_launch_template, "LatestVersionNumber"),
            ),
          ),
          InstancesDistribution=autoscaling.InstancesDistribution(
            OnDemandBaseCapacity=1,
            OnDemandPercentageAboveBaseCapacity=Ref(cluster_on_demand_percentage),
            SpotAllocationStrategy="price-capacity-optimized",
          ),
        ),
        NoValue,
      ),
      LaunchTemplate=If(
        cluster_use_spot,
        NoValue,
        autoscaling.LaunchTemplateSpecification(
          LaunchTemplateId=Ref(ec2_launch_template),
          Version=GetAtt(ec2_launch_template, "LatestVersionNumber"),
        ),
      ),
      MinSize=Ref(cluster_min_size),
      MaxSize=Ref(cluster_max_size),
      DesiredCapacity=Ref(cluster_deised_size),
      Tags=[
        autoscaling.Tag("Name", Join("-", [StackName, "ECS-ASG"]), True),
      ],
      CreationPolicy=policies.CreationPolicy(
        ResourceSignal=policies.ResourceSignal(
          Timeout="PT15M",
        ),
      ),
      UpdatePolicy=policies.UpdatePolicy(
        AutoScalingRollingUpdate=policies.AutoScalingRollingUpdate(
          MinInstancesInService=1,
          MaxBatchSize=1,
          PauseTime="PT15M",
          SuspendProcesses=[
            "HealthCheck",
            "ReplaceUnhealthy",
            "AZRebalance",
            "AlarmNotification",
            "ScheduledActions",
          ],
          WaitOnResourceSignals=True,
        ),
      ),
    ))

    template.add_resource(autoscaling.WarmPool(
      "EC2AutoScalingGroupWarmPool",
      Condition=cluster_should_add_warm_pool,
      AutoScalingGroupName=Ref(ec2_autoscaling_group),
      InstanceReusePolicy=autoscaling.InstanceReusePolicy(
        ReuseOnScaleIn=True,
      ),
    ))

    ecs_capacity_provider = template.add_resource(ecs.CapacityProvider(
      "ECSCapacityProvider",
      AutoScalingGroupProvider=ecs.AutoScalingGroupProvider(
        AutoScalingGroupArn=Ref(ec2_autoscaling_group),
        ManagedScaling=ecs.ManagedScaling(
          MaximumScalingStepSize=4,
          MinimumScalingStepSize=1,
          Status="ENABLED",
          TargetCapacity=Ref(cluster_target_capacity_utilization),
        ),
      ),
    ))

    ecs_capacity_provider_associations = template.add_resource(ecs.ClusterCapacityProviderAssociations(
      "ECSClusterCapacityProviderAssociations",
      Cluster=Ref(ecs_cluster),
      CapacityProviders=[Ref(ecs_capacity_provider)],
      DefaultCapacityProviderStrategy=[ecs.CapacityProviderStrategy(
        Base=1,
        Weight=10,
        CapacityProvider=Ref(ecs_capacity_provider),
      )],
    ))

  else: # if args.launch_type == "EC2"
    ecs_capacity_provider_associations = template.add_resource(ecs.ClusterCapacityProviderAssociations(
      "ECSClusterCapacityProviderAssociations",
      Cluster=Ref(ecs_cluster),
      CapacityProviders=["FARGATE"],
      DefaultCapacityProviderStrategy=[
        ecs.CapacityProviderStrategy(
          Base=1,
          Weight=10,
          CapacityProvider="FARGATE",
        ),
      ],
    ))

# ==============================================================================
# ECS TASK DEFINITION
# ==============================================================================

ecs_task_role = template.add_resource(iam.Role(
  "ECSTaskRole",
  RoleName=Join("-", [StackName, "ecs-task"]),
  Path="/",
  AssumeRolePolicyDocument=aws.PolicyDocument(
    Version="2012-10-17",
    Statement=[aws.Statement(
      Effect=aws.Allow,
      Action=[actions_sts.AssumeRole],
      Principal=aws.Principal("Service", ["ecs-tasks.amazonaws.com"]),
      Condition=aws.Condition([
        aws.ArnLike("aws:SourceArn", Join(":", ["arn:aws:ecs", Region, AccountId, "*"])),
        aws.StringEquals("aws:SourceAccount", AccountId),
      ]),
    )],
  ),
  Policies=[
    iam.Policy(
      PolicyName="cloudwatch",
      PolicyDocument=aws.PolicyDocument(
        Version="2012-10-17",
        Statement=[aws.Statement(
          Effect=aws.Allow,
          Action=[
            actions_logs.CreateLogStream,
            actions_logs.PutLogEvents,
            actions_cloudwatch.PutMetricData,
            actions_cloudwatch.PutMetricStream,
          ],
          Resource=["*"],
        )],
      ),
    ),
    If(
      have_environment_secret_arn,
      iam.Policy(
        PolicyName="secrets_manager-access",
        PolicyDocument=aws.PolicyDocument(
          Version="2012-10-17",
          Statement=[aws.Statement(
            Effect=aws.Allow,
            Action=[
              actions_secretsmanager.GetSecretValue,
              actions_secretsmanager.ListSecretVersionIds,
            ],
            Resource=[Ref(environment_secret_arn)],
          )],
        ),
      ),
      NoValue,
    ),
    If(
      have_environment_systems_manager_parameters_path,
      iam.Policy(
        PolicyName="systems_manager-access",
        PolicyDocument=aws.PolicyDocument(
          Version="2012-10-17",
          Statement=[aws.Statement(
            Effect=aws.Allow,
            Action=[
              actions_ssm.GetParametersByPath,
            ],
            Resource=[Join(
              "",
              [
                "arn:aws:ssm:",
                Region,
                ":",
                AccountId,
                ":parameter",
                Ref(environment_systems_manager_parameters_path)
              ],
            )],
          )],
        ),
      ),
      NoValue,
    ),
    If(
      have_s3_objects,
      iam.Policy(
        PolicyName="s3-access",
        PolicyDocument=aws.PolicyDocument(
          Version="2012-10-17",
          Statement=[aws.Statement(
            Effect=aws.Allow,
            Action=[
              actions_s3.GetObject,
              actions_s3.GetObjectVersion,
            ],
            Resource=Ref(s3_objects),
          )],
        ),
      ),
      NoValue,
    ),
    If(
      have_s3_assume_role_arn,
      iam.Policy(
        PolicyName="iam_role-assume",
        PolicyDocument=aws.PolicyDocument(
          Version="2012-10-17",
          Statement=[aws.Statement(
            Effect=aws.Allow,
            Action=[actions_sts.AssumeRole],
            Resource=Ref(s3_assume_role_arn),
          )],
        ),
      ),
      NoValue,
    ),
    If(
      enable_s3_client_side_decryption,
      iam.Policy(
        PolicyName="kms-decrypt",
        PolicyDocument=aws.PolicyDocument(
          Version="2012-10-17",
          Statement=[aws.Statement(
            Effect=aws.Allow,
            Action=[actions_kms.Decrypt],
            Resource=Join(
              ":",
              [
                "arn:aws:kms:*",
                AccountId,
                "key/*",
              ],
            ),
          )],
        ),
      ),
      NoValue,
    ),
  ],
))

ecs_task_execution_role = template.add_resource(iam.Role(
  "ECSTaskExecutionRole",
  RoleName=Join("-", [StackName, "ecs-task-execution"]),
  Path="/",
  AssumeRolePolicyDocument=aws.PolicyDocument(
    Version="2012-10-17",
    Statement=[aws.Statement(
      Effect=aws.Allow,
      Action=[actions_sts.AssumeRole],
      Principal=aws.Principal("Service", ["ecs-tasks.amazonaws.com"]),
    )],
  ),
  ManagedPolicyArns=[
    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
  ],
))

ecs_task_definition = template.add_resource(ecs.TaskDefinition(
  "ECSTaskDefinition",
  Family=StackName,
  Cpu=Ref(container_cpu),
  Memory=Ref(container_memory) if args.launch_type == "FARGATE" else NoValue,
  RuntimePlatform=ecs.RuntimePlatform(
    CpuArchitecture=FindInMap("Architectures", Ref(cpu_arch), "Arch"),
    OperatingSystemFamily="LINUX",
  ),
  NetworkMode="awsvpc" if args.launch_type == "FARGATE" else "bridge",
  RequiresCompatibilities=[args.launch_type],
  TaskRoleArn=GetAtt(ecs_task_role, "Arn"),
  ExecutionRoleArn=GetAtt(ecs_task_execution_role, "Arn"),
  ContainerDefinitions=[ecs.ContainerDefinition(
    Name="imgproxy",
    Essential=True,
    Image=Ref(docker_image),
    Cpu=Ref(container_cpu),
    MemoryReservation=Ref(container_memory) if args.launch_type == "EC2" else NoValue,
    Environment=[
      ecs.Environment(Name="AWS_REGION", Value=Region),
      ecs.Environment(Name="IMGPROXY_BIND", Value=":8080"),
      ecs.Environment(Name="IMGPROXY_LOG_FORMAT", Value="structured"),
      If(
        have_environment_secret_arn,
        ecs.Environment(Name="IMGPROXY_ENV_AWS_SECRET_ID", Value=Ref(environment_secret_arn)),
        NoValue,
      ),
      If(
        have_environment_secret_arn,
        ecs.Environment(Name="IMGPROXY_ENV_AWS_SECRET_VERSION_ID", Value=Ref(environment_secret_version_id)),
        NoValue,
      ),
      If(
        have_environment_systems_manager_parameters_path,
        ecs.Environment(Name="IMGPROXY_ENV_AWS_SSM_PARAMETERS_PATH", Value=Ref(environment_systems_manager_parameters_path)),
        NoValue,
      ),
      ecs.Environment(Name="IMGPROXY_USE_S3", Value="1"),
      If(
        have_s3_assume_role_arn,
        ecs.Environment(Name="IMGPROXY_S3_ASSUME_ROLE_ARN", Value=Ref(s3_assume_role_arn)),
        NoValue,
      ),
      If(
        enable_s3_multi_region,
        ecs.Environment(Name="IMGPROXY_S3_MULTI_REGION", Value="1"),
        NoValue,
      ),
      If(
        enable_s3_client_side_decryption,
        ecs.Environment(Name="IMGPROXY_S3_USE_DECRYPTION_CLIENT", Value="1"),
        NoValue,
      ),
      If(
        have_path_prefix,
        ecs.Environment(Name="IMGPROXY_PATH_PREFIX", Value=Ref(path_prefix)),
        NoValue,
      ),
      ecs.Environment(Name="IMGPROXY_CLOUD_WATCH_SERVICE_NAME", Value=StackName),
      ecs.Environment(Name="IMGPROXY_CLOUD_WATCH_NAMESPACE", Value="imgproxy"),
      ecs.Environment(Name="IMGPROXY_CLOUD_WATCH_REGION", Value=Region),
    ],
    PortMappings=[ecs.PortMapping(ContainerPort=8080)],
    HealthCheck=ecs.HealthCheck(
      Command=["CMD-SHELL", "imgproxy health"],
      Interval=10,
      Retries=3,
      Timeout=2,
      StartPeriod=5,
    ),
    LogConfiguration=ecs.LogConfiguration(
      LogDriver="awslogs",
      Options={
        "awslogs-group": Ref(log_group),
        "awslogs-region": Region,
        "awslogs-stream-prefix": StackName,
      },
    ),
  )],
))

# ==============================================================================
# LOAD BALANCER
# ==============================================================================

if not args.no_network:
  load_balancer = template.add_resource(loadbalancing.LoadBalancer(
    "LoadBalancer",
    Name=Join("-", [StackName, "ALB"]),
    Subnets=subnet_refs,
    SecurityGroups=[Ref(load_balancer_security_group)],
    Tags= [
      Tag("Name", Join("-", [StackName, "ALB"])),
    ],
  ))

  load_balancer_listener = template.add_resource(loadbalancing.Listener(
    "LoadBalancerListener",
    LoadBalancerArn=Ref(load_balancer),
    Port=80,
    Protocol="HTTP",
    DefaultActions=[
      loadbalancing.Action(
        Type="fixed-response",
        FixedResponseConfig=loadbalancing.FixedResponseConfig(
          ContentType="text/plain",
          MessageBody="Not found",
          StatusCode="404",
        ),
      ),
    ],
  ))

load_balancer_target_group = template.add_resource(loadbalancing.TargetGroup(
  "LoadBalancerTargetGroup",
  Name=StackName,
  VpcId=Ref(vpc),
  Port=80,
  Protocol="HTTP",
  TargetType="ip" if args.launch_type == "FARGATE" else "instance",
  TargetGroupAttributes=[loadbalancing.TargetGroupAttribute(
    Key="load_balancing.algorithm.type",
    Value="least_outstanding_requests",
  )],
  HealthCheckIntervalSeconds=5,
  HealthCheckPath=Join("/", [Ref(path_prefix), "health"]),
  HealthCheckProtocol="HTTP",
  HealthCheckTimeoutSeconds=2,
  HealthyThresholdCount=2,
))

load_balancer_listener_rule = template.add_resource(loadbalancing.ListenerRule(
  "LoadBalancerListenerRule",
  ListenerArn=Ref(load_balancer_listener),
  Priority=1,
  Conditions=[
    loadbalancing.Condition(
      Field="path-pattern",
      Values=[Join("/", [Ref(path_prefix), "*"])],
    ),
    If(
      have_authorization_token,
      loadbalancing.Condition(
        Field="http-header",
        HttpHeaderConfig=loadbalancing.HttpHeaderConfig(
          HttpHeaderName="X-Imgproxy-Auth",
          Values=[Ref(authorization_token)],
        ),
      ),
      NoValue,
    ),
  ],
  Actions=[loadbalancing.ListenerRuleAction(
    Type="forward",
    TargetGroupArn=Ref(load_balancer_target_group),
  )],
))

# ==============================================================================
# ECS SERVICE
# ==============================================================================

ecs_service = template.add_resource(ecs.Service(
  "ECSService",
  DependsOn=list(filter(
    lambda x: x is not None,
    [load_balancer_listener_rule, ecs_capacity_provider_associations],
  )),
  ServiceName=StackName,
  Cluster=Ref(ecs_cluster),
  DesiredCount=Ref(task_desired_count),
  TaskDefinition=Ref(ecs_task_definition),
  NetworkConfiguration=ecs.NetworkConfiguration(
    AwsvpcConfiguration=ecs.AwsvpcConfiguration(
      AssignPublicIp="ENABLED",
      SecurityGroups=[Ref(ecs_host_security_group)],
      Subnets=subnet_refs,
    ),
  ) if args.launch_type == "FARGATE" else NoValue,
  LoadBalancers=[ecs.LoadBalancer(
    ContainerName="imgproxy",
    ContainerPort=8080,
    TargetGroupArn=Ref(load_balancer_target_group),
  )],
))

# ==============================================================================
# AUTOSCALING
# ==============================================================================

autoscaling_scalable_target = template.add_resource(applicationautoscaling.ScalableTarget(
  "AutoscalingScalableTarget",
  MaxCapacity=Ref(task_max_count),
  MinCapacity=Ref(task_min_count),
  ResourceId=Join("/", ["service", Ref(ecs_cluster), GetAtt(ecs_service, "Name")]),
  RoleARN=Join(":", ["arn:aws:iam:", AccountId, "role/aws-service-role/ecs.application-autoscaling.amazonaws.com/AWSServiceRoleForApplicationAutoScaling_ECSService"]),
  ScalableDimension="ecs:service:DesiredCount",
  ServiceNamespace="ecs",
))

autoscaling_scaling_out_policy = template.add_resource(applicationautoscaling.ScalingPolicy(
  "AutoscalingScalingOutPolicy",
  PolicyName=Join("-", [StackName, "Scaling-Out-Policy"]),
  PolicyType="StepScaling",
  ScalingTargetId=Ref(autoscaling_scalable_target),
  StepScalingPolicyConfiguration=applicationautoscaling.StepScalingPolicyConfiguration(
    AdjustmentType="PercentChangeInCapacity",
    Cooldown=120 if args.launch_type == "EC2" else 30,
    MetricAggregationType="Average",
    StepAdjustments=[
      applicationautoscaling.StepAdjustment(
        MetricIntervalLowerBound=0,
        MetricIntervalUpperBound=25,
        ScalingAdjustment=20,
      ),
      applicationautoscaling.StepAdjustment(
        MetricIntervalLowerBound=25,
        MetricIntervalUpperBound=50,
        ScalingAdjustment=40,
      ),
      applicationautoscaling.StepAdjustment(
        MetricIntervalLowerBound=50,
        MetricIntervalUpperBound=75,
        ScalingAdjustment=60,
      ),
      applicationautoscaling.StepAdjustment(
        MetricIntervalLowerBound=75,
        MetricIntervalUpperBound=100,
        ScalingAdjustment=80,
      ),
      applicationautoscaling.StepAdjustment(
        MetricIntervalLowerBound=100,
        ScalingAdjustment=100,
      ),
    ],
  ),
))

autoscaling_scaling_in_policy = template.add_resource(applicationautoscaling.ScalingPolicy(
  "AutoscalingScalingInPolicy",
  PolicyName=Join("-", [StackName, "Scaling-In-Policy"]),
  PolicyType="StepScaling",
  ScalingTargetId=Ref(autoscaling_scalable_target),
  StepScalingPolicyConfiguration=applicationautoscaling.StepScalingPolicyConfiguration(
    AdjustmentType="PercentChangeInCapacity",
    Cooldown=600 if args.launch_type == "EC2" else 300,
    MetricAggregationType="Average",
    StepAdjustments=[applicationautoscaling.StepAdjustment(
      MetricIntervalUpperBound=0,
      ScalingAdjustment=-10,
    )],
  ),
))

template.add_resource(cloudwatch.Alarm(
  "AutoscalingHighConcurrencyUsageAlarm",
  AlarmName=Join("-", [GetAtt(ecs_service, "Name"), "High-Concurrency-Usage"]),
  AlarmDescription=Join(
    " ",
    [
      "High concurrency utilization for service",
      GetAtt(ecs_service, "Name"),
      "in environment",
      StackName,
    ],
  ),
  MetricName="ConcurrencyUtilization",
  Namespace="imgproxy",
  Dimensions=[cloudwatch.MetricDimension(
    Name="ServiceName",
    Value=GetAtt(ecs_service, "Name"),
  )],
  Statistic="Average",
  Period=30 if args.launch_type == "EC2" else 10,
  EvaluationPeriods=2,
  Threshold=80,
  ComparisonOperator="GreaterThanThreshold",
  AlarmActions=[Ref(autoscaling_scaling_out_policy)],
))

template.add_resource(cloudwatch.Alarm(
  "AutoscalingLowConcurrencyUsageAlarm",
  AlarmName=Join("-", [GetAtt(ecs_service, "Name"), "Low-Concurrency-Usage"]),
  AlarmDescription=Join(
    " ",
    [
      "Low concurrency utilization for service",
      GetAtt(ecs_service, "Name"),
      "in environment",
      StackName,
    ],
  ),
  MetricName="ConcurrencyUtilization",
  Namespace="imgproxy",
  Dimensions=[cloudwatch.MetricDimension(
    Name="ServiceName",
    Value=GetAtt(ecs_service, "Name"),
  )],
  Statistic="Average",
  Period=30,
  EvaluationPeriods=20 if args.launch_type == "EC2" else 10,
  Threshold=50,
  ComparisonOperator="LessThanThreshold",
  AlarmActions=[Ref(autoscaling_scaling_in_policy)],
))

# ==============================================================================
# CLOUDFRONT DISTRIBUTION
# ==============================================================================

if not args.no_network:
  cloudfront_cache_policy = template.add_resource(cloudfront.CachePolicy(
    "CloudFrontCachePolicy",
    Condition=deploy_cloudfront,
    CachePolicyConfig=cloudfront.CachePolicyConfig(
      Name=Join("-", [StackName, "cache-policy"]),
      DefaultTTL=31536000,
      MaxTTL=31536000,
      MinTTL=0,
      ParametersInCacheKeyAndForwardedToOrigin=cloudfront.ParametersInCacheKeyAndForwardedToOrigin(
        CookiesConfig=cloudfront.CacheCookiesConfig(CookieBehavior="none"),
        EnableAcceptEncodingBrotli=False,
        EnableAcceptEncodingGzip=False,
        HeadersConfig=cloudfront.CacheHeadersConfig(
          HeaderBehavior="whitelist",
          Headers=["Accept"],
        ),
        QueryStringsConfig=cloudfront.CacheQueryStringsConfig(QueryStringBehavior="none"),
      )
    ),
  ))

  cloudfront_distribution = template.add_resource(cloudfront.Distribution(
    "CloudFrontDistribution",
    Condition=deploy_cloudfront,
    DistributionConfig=cloudfront.DistributionConfig(
      Enabled=True,
      Origins=[cloudfront.Origin(
        DomainName=GetAtt(load_balancer, "DNSName"),
        Id=Join("-", [StackName, "origin"]),
        CustomOriginConfig=cloudfront.CustomOriginConfig(
          HTTPPort=80,
          OriginProtocolPolicy="http-only",
        ),
        OriginPath=Ref(path_prefix),
        OriginCustomHeaders=If(
          have_authorization_token,
          [cloudfront.OriginCustomHeader(
            HeaderName="X-Imgproxy-Auth",
            HeaderValue=Ref(authorization_token),
          )],
          NoValue,
        ),
        OriginShield=cloudfront.OriginShield(
          Enabled=True,
          OriginShieldRegion=Region,
        ),
      )],
      DefaultCacheBehavior=cloudfront.DefaultCacheBehavior(
        TargetOriginId=Join("-", [StackName, "origin"]),
        CachePolicyId=Ref(cloudfront_cache_policy),
        ViewerProtocolPolicy="redirect-to-https",
      ),
      PriceClass="PriceClass_All",
      ViewerCertificate=cloudfront.ViewerCertificate(
        CloudFrontDefaultCertificate=True,
      ),
    ),
  ))

# ==============================================================================
# OUTPUTS
# ==============================================================================

if not args.no_network:
  template.add_output(Output(
    "DirectURL",
    Description="The direct URL endpoint for imgproxy",
    Value=GetAtt(load_balancer, "DNSName"),
  ))

  template.add_output(Output(
    "CloudFrontURL",
    Description="The CloudFront endpoint for imgproxy",
    Value=GetAtt(cloudfront_distribution, "DomainName"),
    Condition=deploy_cloudfront,
  ))

# ==============================================================================
# WRITE THE RESULT
# ==============================================================================

if args.format == "json":
  out = template.to_json(sort_keys=False)
else:
  out = template.to_yaml(sort_keys=False)

if args.output == None:
  print(out)
else:
  file = open(args.output, "w")
  file.write(out)
  file.close()
