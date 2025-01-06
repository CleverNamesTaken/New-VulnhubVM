# New-VulnhubVM
Port of https://github.com/0xBEN/Proxmox-Lab-Scripts/blob/master/New-VulnhubVM.ps1 to Python

# Installation

sudo apt install python3-venv
python3 -m venv venv_newVulnHub
./venv_newVulnHub/bin/pip3 install patool requests argparse

# Usage

```
./New-VulnhubVM.py -h
options:
  -h, --help            show this help message and exit
  -u URL, --url URL     URL to Vulnhub machine to download.
  -s STORAGE, --storage STORAGE
                        Proxmox storage volume to save the VM.
  -i ID, --id ID        VMID to use for newly created VM.
  -n NETWORK, --network NETWORK
                        Network interface to add to the newly created VM. Should have DHCP.
```

`./New-VulnhubVM.py -s external -n vulnhub2 -i 421 -u 'https://download.vulnhub.com/jangow/jangow-01-1.0.1.ova'`

Then `qm start 421`.

Note that the network interface to add needs to have DHCP.  I followed this guide: https://pve.proxmox.com/wiki/Setup_Simple_Zone_With_SNAT_and_DHCP

                        
