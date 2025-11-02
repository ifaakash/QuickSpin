## How to deploy the VM?

### GITBOOK DOCS
- NAT with EIP [https://aakashs-organization-3.gitbook.io/devops-doks/group-2/aws/nat-with-eip]
- How does SSM works in AWS [https://aakashs-organization-3.gitbook.io/devops-doks/group-2/aws/how-does-ssm-works-in-aws]

### PLAN
- [x] Private Instance will need an IAM role granting Session Manager role to it
- [x] Allow connection to public Instance with Session Manager only, for better security
- [x] How to deploy 'N' public and 'N' private instance
- [x] Verfiy if the private Instance is able to download the dependencies
- [x] Test Configuration with three Instances
- [ ] Does the EIP gets removed when instance is removed?

### TASKS
- [x] Create an IAM role for System Manager Session Manager
- [x] For private instace, create VPC endpoints
- [x] Security group for public instance allowing outbount to Session Manager ( over HTTPS )
- [x] Allow inbound from user IP for public instance, and outbound to 0.0.0.0:443 ( for SSM )

- [x] (HIGH PRIORITY) One ENI can be attached to single instance, find a way to attach multiple ENI to single instance
- [ ] (HIGH PRIORITY) Create a common key-pair, and attach that to all instances created --> ON HOLD (SSM IS IMPLEMENTED)
- [x] (HIGH PRIORITY) Route table attachment to the Subnet of the Instance
- [x] (HIGH PRIORITY) Increase size of public Instance and check connectivity using System
- [x] (HIGH PRIORITY) Check if the public Instance gets a public IP when connected to Public Subnet, without EIP
- [x] (HIGH PRIORITY) Check if apache is accessible from the Instance public IP, that is accessible via Public IP ( without EIP )
- [x] (HIGH PRIORITY) The Private subnet, need to have NAT Gateway attached to it, what if we deploy multiple private subnet?

### TESTED
- The Instance deployed, have a name to denote if they are public or private
- The public Instance, attached to IGW, is able to connect with Internet ( verified via ping 8.8.8.8 )
- The public Instance, attached to IGW, is having SSM agent running, and the only way to connect with it, is via Session Manager
- The private Instance, is able to ping the internet, once the NAT Gateway is deployed in the public subnet

```
instances:
  count: 1
  user_ip: "49.36.144.148"
```


### PATCHES
- [ ] `ami-0360c520857e3138f` comes with pre-installed SSM installed in it. If the user customize this, then the user will need to install SSM agent manually. But, that cannot be done, without logging into the instance ( one way is `user-data` )
