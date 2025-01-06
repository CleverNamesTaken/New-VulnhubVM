#!./venv_newVulnHub/bin/python3

''' Python script to download a vulnhub VM and add it to a proxmox server '''

''' Dependencies: arpgarse, patool, requests '''
import argparse
import patoolib
import requests
import subprocess
import tempfile
import sys
from pathlib import Path


# Function to parse command line arguments
def get_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('-u','--url',help="URL to Vulnhub machine to download.",required=True)
    parser.add_argument('-s','--storage',help="Proxmox storage volume to save the VM.",required=True)
    parser.add_argument('-i','--id',help="VMID to use for newly created VM.",required=False)
    parser.add_argument('-n','--network',help="Network interface to add to the newly created VM.  Should have DHCP.",required=True)
    args = parser.parse_args()
    return(args)

# Function to download the vm
def download_vm(url):
    vm_archive = url.split('/')[-1]
    temp_dir = tempfile.TemporaryDirectory().name
    try:
        print(f"[+] Downloading {vm_archive}.  This could take a while...")
        subprocess.run(f'mkdir -p {temp_dir}',shell=True)
        with requests.get(url, stream=True) as response:
            response.raise_for_status()
            with open(f"{temp_dir}/{vm_archive}", "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
        print(f"[+] Downloaded {vm_archive} to {temp_dir}.")
    except Exception as e:
        print(f"[!] Failed to download {vm_archive}.")
        print(e) 
        clean_up(temp_dir)
        sys.exit(1)
    return (temp_dir,vm_archive)

# Function to extract the archive file.  Currently supports...
def extract_vm(temp_directory,archiveFile):
    print("[+] Extracting files")
    patoolib.extract_archive(f"{temp_directory}/{archiveFile}", outdir=temp_directory,verbosity=-1)
    print("[+] Extracted files.  Locating ovf and vmdk files")
    #We assume we only have one vmdk and one ovf file here.
    vmdk_file = find_files_with_extension(temp_directory,'vmdk')[0]
    ovf_file = find_files_with_extension(temp_directory,'ovf')[0]
    # nested archive files?

    return (vmdk_file,ovf_file)


# Function to look a directory and find files with a matching extension
def find_files_with_extension(directory, extension):
    # Ensure the extension starts with a dot
    if not extension.startswith('.'):
        extension = '.' + extension
    return [file.as_posix() for file in Path(directory).iterdir() if file.suffix.lower() == extension.lower()]

# Function to create the VM using the ovf and vmdk files
def create_vm(virtualDiskFile,ovf,storageLocation,VMID):
    print("[+] Creating VM")
    # Check the VMID
        #if (Invoke-Command -ScriptBlock {qm status $id 2>/dev/null}) {
    subprocess.run(f'qm importovf {VMID} "{ovf}" {storageLocation} --format qcow2',shell=True, stdout=subprocess.DEVNULL)
    subprocess.run(f'qm importdisk {VMID} "{virtualDiskFile}" {storageLocation} --format qcow2',shell=True, stdout=subprocess.DEVNULL)
    return

# Function to configure the VM -- attach the disk, set the correct boot order and network interface
def configure_vm(VMID,storageLocation,bridge):
    print("[+] Configuring VM.")
    subprocess.run(f'qm set {VMID} -sata0 "{storageLocation}:{VMID}/vm-{VMID}-disk-1.qcow2"',shell=True, stdout=subprocess.DEVNULL)
    subprocess.run(f'qm set {VMID} -boot "order=sata0"',shell=True, stdout=subprocess.DEVNULL)
    subprocess.run(f'qm set {VMID} -net0 "model=virtio,bridge={bridge}"',shell=True, stdout=subprocess.DEVNULL)
    return

# Function to clean up anything created by this script
def clean_up(directory):
    print("[+] Cleaning up")
    subprocess.run(f'rm -rf {directory}',shell=True)
    return

args = get_arguments()
temp_dir,vm_archive = download_vm(args.url)
vmdk_file,ovf_file = extract_vm(temp_dir,vm_archive)
create_vm(vmdk_file,ovf_file,args.storage,args.id)
configure_vm(args.id,args.storage,args.network)
clean_up(temp_dir)
