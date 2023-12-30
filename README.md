<p align="center">
  <a href="https://imgproxy.net">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg?sanitize=true">
      <source media="(prefers-color-scheme: light)" srcset="assets/logo-light.svg?sanitize=true">
      <img alt="imgproxy logo" src="assets/logo-light.svg?sanitize=true">
    </picture>
  </a>
</p>

<h4 align="center">
  <a href="https://imgproxy.net">Website</a> |
  <a href="https://imgproxy.net/blog/">Blog</a> |
  <a href="https://docs.imgproxy.net">Documentation</a> |
  <a href="https://imgproxy.net/#pro">imgproxy Pro</a> |
  <a href="https://hub.docker.com/r/darthsim/imgproxy/">Docker</a> |
  <a href="https://twitter.com/imgproxy_net">Twitter</a> |
  <a href="https://discord.gg/5GgpXgtC9u">Discord</a>
</h4>

---

[imgproxy](https://imgproxy.net) is a fast and secure standalone server for resizing and converting remote images. The main principles of imgproxy are simplicity, speed, and security.

This repository contains a [troposphere](https://github.com/cloudtools/troposphere) script that generates an [AWS CloudFormation](https://aws.amazon.com/cloudformation/) template to deploy imgproxy to [AWS ECS](https://aws.amazon.com/ecs/). The script can generate different templates depending on your needs.

## Using pre-built templates

We prepared a few pre-built templates that you can use right away. Just click on a link, set the required options, and you're ready to process your images.

### Full intallation

These templates create all the required resources, plug-n-play:

- Networks (VPC, subnetworks, internet gateway, routing tables, etc)
- Security groups
- Application Load Balancer
- ECS cluster
- ECS capacity provider (Fargate or EC2)
- EC2 autoscaling group (EC2 only)
- ECS task definition
- ECS service
- Autoscaling rules
- CloudFront distribution (optional)

| Launch type |    |
|-------------|----|
| Fargate     | [![](assets/launch-stack.svg)](https://console.aws.amazon.com/cloudformation/home#/stacks/new?stackName=imgproxy&templateURL=https://imgproxy-cf.s3.amazonaws.com/latest/ecs-fargate-full.yml) |
| EC2         | [![](assets/launch-stack.svg)](https://console.aws.amazon.com/cloudformation/home#/stacks/new?stackName=imgproxy&templateURL=https://imgproxy-cf.s3.amazonaws.com/latest/ecs-ec2-full.yml) |

### Intallation without networking

If you already have an Application Load Balancer and networks configured, you may want your imgproxy installation to use them. These templates create all the required resources except for networking:

- ECS cluster
- ECS capacity provider (Fargate or EC2)
- EC2 autoscaling group (EC2 only)
- ECS task definition
- ECS service
- Autoscaling rules

These templates require the following resources to be provided via template parameters:

- VPC
- Subnetworks
- Security group
- Application Load Balancer listener

| Launch type |    |
|-------------|----|
| Fargate     | [![](assets/launch-stack.svg)](https://console.aws.amazon.com/cloudformation/home#/stacks/new?stackName=imgproxy&templateURL=https://imgproxy-cf.s3.amazonaws.com/latest/ecs-fargate-no-network.yml) |
| EC2         | [![](assets/launch-stack.svg)](https://console.aws.amazon.com/cloudformation/home#/stacks/new?stackName=imgproxy&templateURL=https://imgproxy-cf.s3.amazonaws.com/latest/ecs-ec2-no-network.yml) |

### Intallation without cluster and networking

If you already have an ECS cluster, you may want to deploy imgproxy to it. These templates create all the required resources except for the cluster and networking:

- ECS task definition
- ECS service
- Autoscaling rules

These templates require the following resources to be provided via template parameters:

- VPC
- Subnetworks (Fargate only)
- Security group (Fargate only)
- Application Load Balancer listener
- ECS cluster

> [!IMPORTANT]
> The created service will use the default capacity provider of the cluster. If you want to use a different capacity provider, you need to modify the template.

| Launch type |    |
|-------------|----|
| Fargate     | [![](assets/launch-stack.svg)](https://console.aws.amazon.com/cloudformation/home#/stacks/new?stackName=imgproxy&templateURL=https://imgproxy-cf.s3.amazonaws.com/latest/ecs-fargate-no-cluster.yml) |
| EC2         | [![](assets/launch-stack.svg)](https://console.aws.amazon.com/cloudformation/home#/stacks/new?stackName=imgproxy&templateURL=https://imgproxy-cf.s3.amazonaws.com/latest/ecs-ec2-no-cluster.yml) |

## Building your own template

If you want to customize the template, you can build it yourself. You need to have [Python](https://www.python.org/) and [pip](https://pip.pypa.io/en/stable/installing/) installed.

1. Clone this repository:

    ```bash
    git clone https://github.com/imgproxy/imgproxy-cloudformation.git
    ```
2. Install dependencies:

    ```bash
    pip install -r requirements.txt
    ```
3. Run the script:

    ```bash
    ./template.py
    ```

If you want the script to write the template to a file instead of printing it to stdout, use the `--output` option:

```bash
./template.py --output template.yml
```

By default, the script will generate a template for Fargate. You can change the launch type by passing the `--launch-type` option:

```bash
./template.py --launch-type ec2
```

If you don't want the template to include networking resources, use the `--no-network` option:

```bash
./template.py --no-network
```

If you don't want the template to include the ECS cluster, use the `--no-cluster` option:

```bash
./template.py --no-cluster
```

> [!IMPORTANT]
> Since the ECS cluster's default capacity provider may be configured to use existing networking resources such as VPC, subnetworks, and security groups, the `--no-cluster` option requires the `--no-network` option to be used as well.

See the script's help (`./template.py -h`) for more options.

## License

imgproxy-cloudformation is licensed under the MIT license.

See [LICENSE](https://github.com/imgproxy/imgproxy-cloudformation/blob/master/LICENSE) for the full license text.

## Security Contact

To report a security vulnerability, please contact us at security@imgproxy.net. We will coordinate the fix and disclosure.
