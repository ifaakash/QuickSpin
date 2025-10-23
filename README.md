## How to deploy the VM?

### PLAN
- [ ] Private Instance will need an IAM role granting Session Manager role to it
- [ ] Allow connection to public Instance with Session Manager only, for better security
- [ ] How to deploy 'N' public and 'N' private instance
  - If the instances field is a list of instance, then we can

### TASKS
- [x] Create an IAM role for System Manager Session Manager
- [ ] For private instace, create VPC endpoints
- [ ] Security group for public instnace allowing outbount to Session Manager ( over HTTPS )
- [ ] Allow inbound from user IP for public instance, and outbound to 0.0.0.0:443 ( for SSM )

- [ ] (HIGH PRIORITY) Create a common key-pair, and attach that to all instances created
- [ ] (HIGH PRIORITY) One ENI can be attached to single instance, find a way to attach multiple ENI to single instance
- [ ] (HIGH PRIORITY) Route table attachment to the Subnet of the Instance
- [ ] (HIGH PRIORITY) Increase size of public Instance and check connectivity using System
- [ ] (HIGH PRIORITY) Check if the public Instance gets a public IP when connected to Public Subnet, without EIP

```
instances:
  count: 1
  user_ip: "49.36.144.148"
```


### PATCHES
- [ ] `ami-0360c520857e3138f` comes with pre-installed SSM installed in it. If the user customize this, then the user will need to install SSM agent manually. But, that cannot be done, without logging into the instance ( one way is `user-data` )
