# How to integrate ansbile into QuickSpin

## Login to VM using the Key pair
- [] Generate a key pair using terraform
- [] Generate the private key corresponding to the public key
- [] Store the private key to the Secret Manager
- [] Update the workflow to fetch the IP address of the VM

## Key Points
- The key pair will be same for all the VM
- We will just need the IP address of the VM, keeping the KP same and login to the VM
