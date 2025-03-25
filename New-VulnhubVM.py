#!./venv_newVulnHub/bin/python3
''' Python script to download a vulnhub VM and add it to a proxmox server '''
import argparse
import subprocess
import tempfile
import os
import sys
import time
import json
import logging
from pathlib import Path
import requests
import patoolib

# Configure logging
logging.basicConfig(
    filename='new-vulnhubVM.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def get_arguments():
    ''' Parse command line arguments '''
    parser = argparse.ArgumentParser()
    parser.add_argument('-u','--url',help="URL to Vulnhub machine to download.",required=True)
    parser.add_argument('-s','--storage',
                        help="Proxmox storage volume.  Run 'pvesm status' if you are unsure.",
                        required=True)
    parser.add_argument('-i','--id',help="VMID to use for newly created VM.",required=False)
    parser.add_argument('-n','--network',
                        help="VM network interface from 'pvesh ls /cluster/sdn/vnets'."
                        ,required=True)
    return parser.parse_args()

def validate_parameters(proxmox_storage,proxmox_vlan):
    ''' Check if the storage and vlan provided by the user are legit values '''
    storage_list = subprocess.run("pvesm status | awk '/dir/{print $1}'",
                               shell=True,capture_output=True,text=True,
                               check=True).stdout.strip().split('\n')
    if proxmox_storage not in storage_list:
        print(f"[-] {proxmox_storage} is not a valid storage volume. \
              Run 'pvesm status' to see valid volumes.")
        sys.exit(1)
    #Linux bridges would also probably work, but this is only looking for SDN vnets
    vlan_list = subprocess.run("pvesh ls /cluster/sdn/vnets | awk '{print $2}'",
                               shell=True,capture_output=True,text=True,
                               check=True).stdout.strip().split('\n')
    if proxmox_vlan not in vlan_list:
        print(f"[-] {proxmox_vlan} is not a valid SDN VLAN.\
                Run 'pvesh ls /cluster/sdn/vnets' to see valid vlans.")
        sys.exit(1)

def download_vm(url,tmp_dir):
    ''' Download the specified resource '''
    archive = url.split('/')[-1]
    try:
        print(f"[+] Downloading {url}.  This could take a while...")
        subprocess.run(f'mkdir -p {tmp_dir}',shell=True,check=True)
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with open(f"{tmp_dir}/{archive}", "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
        print(f"[+] Downloaded {archive} to {tmp_dir}.")
        logging.info(f"Downloaded {archive} to {tmp_dir}.")
    except requests.exceptions.RequestException as e:
        print(f"[-] Failed to download {archive}. See log for more details.")
        logging.info(f"Failed to download {archive}. -{e}")
        clean_up(tmp_dir)
        sys.exit(1)
    return archive

def extract_vm(archive,temp_directory):
    ''' Extract the archive file, if there is one.'''
    #Check if we downloaded a vmdk
    if Path(archive).suffix.lower() == '.vmdk':
        logging.info(f"{archive} is a vmdk file.  No extraction necessary.")
        vmdk = archive
        ovf = False
    else:
        print("[+] Extracting files")
        patoolib.extract_archive(f"{archive}", outdir=temp_directory,verbosity=-1)
        print("[+] Extracted files.  Locating ovf and vmdk files")
        logging.info(f"{archive} extracted.")
        #We assume we only have one vmdk and one ovf file here.
        try:
            vmdk = find_files_with_extension(temp_directory,'vmdk')[0]
        except IndexError:
            print("[-] No vmdk file found.  Checking if there are more archive files.")
            logging.error(f"No VMDK found in {archive}. Looking for more archive files.")
            #This is just looking for ova.  What if there is more rar, or 7z, or zip?
            new_archive_file = find_files_with_extension(temp_directory,'ova')[0]
            vmdk,ovf = extract_vm(new_archive_file,temp_directory)
        try:
            ovf = find_files_with_extension(temp_directory,'ovf')[0]
        except IndexError:
            print("[-] No ovf file found.")
            logging.error(f"No ovf found in {archive}.")
            ovf = False
    return (vmdk,ovf)


def find_files_with_extension(directory, extension):
    '''Search a directory and find files with a matching extension'''
    if not extension.startswith('.'):
        extension = '.' + extension
    matching_files = []
    for file in Path(directory).rglob('*'):
        if file.suffix.lower() == extension.lower():
            matching_files.append(file.as_posix())
    return matching_files


def renamed_file(file_with_spaces):
    safe_name = file_with_spaces.replace(" ","_").replace(":","-")
    try:
        subprocess.run(f"mv '{file_with_spaces}' {safe_name}",
           shell=True, stdout=subprocess.DEVNULL,check=True)
    except:
        safe_name = file_with_spaces
    return safe_name

def create_vm(virtual_disk_file,ovf,storage_location,vm_id,machine_name):
    ''' Create the VM using the ovf and vmdk files. '''
    print("[+] Creating VM")
    try:
        if ovf is not False:
            logging.info(f"Building VM from {ovf}.")
            if " " not in ovf:
                subprocess.run(f'qm importovf {vm_id} "{ovf}" {storage_location} --format qcow2',
                           shell=True, stdout=subprocess.DEVNULL,check=True)
            else:
                renamed_ovf = renamed_file(ovf)
                subprocess.run(f"cd {temp_dir} && qm importovf {vm_id} '{renamed_ovf}' {storage_location} --format qcow2",
                           shell=True, stdout=subprocess.DEVNULL,check=True)
            subprocess.run(f'qm set {vm_id} -name "{machine_name}"',
                           shell=True, stdout=subprocess.DEVNULL,check=True)
        else:
            logging.info(f"No ovf found in for {machine_name}.  Building dummy VM.")
            subprocess.run(f'qm create {vm_id} --storage "{storage_location}" --memory 1024 --cores 1',
                           shell=True, stdout=subprocess.DEVNULL,check=True)
        print("[+] Created VM")
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with error: {e.stderr}")
        raise
    print("[+] Loading virtual disk to VM")
    try:
        logging.info(f"Loading {virtual_disk_file}.")
        subprocess.run(f'qm importdisk {vm_id} "{virtual_disk_file}" {storage_location} --format qcow2',
                       shell=True, stdout=subprocess.DEVNULL,check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with error: {e.stderr}")
        raise

def configure_vm(vm_id,storage,bridge,ovf):
    ''' Configure the VM, including the following steps
            attach the disk
            set the correct boot order
            set the network interface '''

    print("[+] Configuring VM.")
    try:
        logging.info(f"Loading boot disk.")
        if ovf is not False:
            subprocess.run(f'qm set {vm_id} -sata0 "{storage}:{vm_id}/vm-{vm_id}-disk-1.qcow2"',
                           shell=True, stdout=subprocess.DEVNULL,check=True)
        else:
            subprocess.run(f'qm set {vm_id} -sata0 "{storage}:{vm_id}/vm-{vm_id}-disk-0.qcow2"',
                           shell=True, stdout=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with error: {e.stderr}")
        raise
    try:
        logging.info(f"Changing boot order.")
        subprocess.run(f'qm set {vm_id} -boot "order=sata0"',
                       shell=True, stdout=subprocess.DEVNULL,check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with error: {e.stderr}")
        raise
    try:
        logging.info(f"Adding {bridge} interface.")
        subprocess.run(f'qm set {vm_id} -net0 "model=virtio,bridge={bridge}"',
                       shell=True, stdout=subprocess.DEVNULL,check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with error: {e.stderr}")
        raise

def clean_up(directory):
    ''' Clean up anything created by this script '''
    print("[+] Cleaning up downloaded files.")
    #subprocess.run(f'rm -rf {directory}',shell=True,check=True)

def find_vmid():
    ''' Look at the current VMIDs and pick an available one '''
    try:
        vmid_list = subprocess.run("qm list | awk '{print $1}' | grep '^4.'",
                               shell=True,capture_output=True,text=True,
                               check=True).stdout.strip().split('\n')
    except:
        vmid_list=[]
    # Convert them to numbers
    vmid_list = list(map(int, vmid_list))
    start_number = 400
    max_number = 254 #Maximum number of VMs
    vmid_list.append(start_number)
    vmid_list.sort()
    for i in range(start_number,start_number+max_number,1):
        if i not in vmid_list:
            return i

def check_vmid_available(vm_id):
    ''' Check if the selected VMID is available. '''
    vmid_list = subprocess.run("qm list | awk '{print $1}' | grep '^4.'",
        shell=True,capture_output=True,text=True,
        check=True).stdout.strip().split('\n')
    vmid_list = list(map(int, vmid_list))
    if int(vm_id) in vmid_list:
        print(f"[!] {vm_id} already exists.  Please select another VMID.")
        sys.exit(1)


def complete(virtual_machine_id,vm):
    ''' Pretty message to user. '''

    print(f"[!] {vm} has been loaded.  Start it with the following command")
    print(f"qm start {virtual_machine_id}")

def check_networking(vm_id):
    ''' see if the vm comes up '''
    subprocess.run(f"qm start {vm_id}",shell=True,check=True)
    print("[+] Started VM.  Waiting 60 seconds for it to come online.")
    time.sleep(60)
    #Grab IP from config to see if we can ping it
    with open("/etc/pve/sdn/mac-cache.json","r") as f:
        mac_cache = json.loads(f.read())
    #Grab mac from qm command
    target_mac = subprocess.run(f"qm config {vm_id} | awk -F '[=,\,]' '/net0/ {{print $2}}'",
       shell=True,capture_output=True,text=True,
       check=True).stdout[:-1]
    #Look for mac in mac_cache
    target_ip =mac_cache['macs'][target_mac]["ip4"]
    #Try to ping IP
    try:
        subprocess.run(f"ping -c 1 {target_ip}",
       shell=True,capture_output=True,text=True,
       check=True).stdout[:-1]
        print(f"[+] Success pinging {target_ip}")
    except:
        print(f"[!] Failed to ping {target_ip}.  Might need some more massaging.")
        subprocess.run(f"qm stop {vm_id}",shell=True,check=True)

args = get_arguments()

if not args.id:
    print("[!] No VMID provided.  Let me find one for you...")
    vmid = find_vmid()
    print(f"[!] {str(vmid)} has been selected.")
else:
    vmid = args.id
    check_vmid_available(vmid)

vm_name = args.url.split('/')[3]

logging.info(f"VMID: {vmid} for {args.url}")

validate_parameters(args.storage,args.network)

with tempfile.TemporaryDirectory() as temp_dir:
    vm_archive = download_vm(args.url,temp_dir)
    ARCHIVE_FILE = f"{temp_dir}/{vm_archive}"
    vmdk_file,ovf_file = extract_vm(ARCHIVE_FILE,temp_dir)
    if ovf_file != False:
        old_vmdk = os.path.basename(vmdk_file)
        vmdk_file = renamed_file(vmdk_file)
        subprocess.run(f"sed -i 's^{old_vmdk}^{os.path.basename(vmdk_file)}^g' '{ovf_file}'",shell=True,check=True)
    create_vm(vmdk_file,ovf_file,args.storage,vmid,vm_name)
    configure_vm(vmid,args.storage,args.network,ovf_file)
    clean_up(temp_dir)
    complete(vmid,vm_archive)
    check_networking(vmid)
