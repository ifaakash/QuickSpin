## How to deploy the VM?

### PLAN
1. Private Instance will need an IAM role granting Session Manager role to it
2. Allow connection to public Instance with Session Manager only, for better security
3. How to deploy 'N' public and 'N' private instance
   - If the instances field is a list of instance, then we can

### TASKS
1. Create an IAM role for System Manager Session Manager
2. For private instace, create VPC endpoints
3. Security group for public instnace allowing outbount to Session Manager ( over HTTPS )
4. Allow inbound from user IP for public instance, and outbound to 0.0.0.0:443 ( for SSM )

```
instances:
  count: 1
  user_ip: "49.36.144.148"
```


### PATCHES
1. `ami-0360c520857e3138f` comes with pre-installed SSM installed in it. If the user customize this, then the user will need to install SSM agent manually. But, that cannot be done, without logging into the instance ( one way is `user-data` )
