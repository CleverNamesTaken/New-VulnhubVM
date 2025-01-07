#!./venv_newVulnHub/bin/python3
''' Python script to download a vulnhub VM and add it to a proxmox server '''
import argparse
import subprocess
import tempfile
import sys
from pathlib import Path
import requests
import patoolib


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

def download_vm(url,tmp_dir):
    ''' Download the specified resource '''
    archive = url.split('/')[-1]
    try:
        print(f"[+] Downloading {archive}.  This could take a while...")
        subprocess.run(f'mkdir -p {tmp_dir}',shell=True,check=True)
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with open(f"{tmp_dir}/{archive}", "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
        print(f"[+] Downloaded {archive} to {tmp_dir}.")
    except requests.exceptions.RequestException as e:
        print(f"[-] Failed to download {archive}.")
        print(e)
        clean_up(tmp_dir)
        sys.exit(1)
    return archive

def extract_vm(archive,temp_directory):
    ''' Extract the archive file, if there is one.'''
    #Check if we downloaded a vmdk
    if Path(archive).suffix.lower() == '.vmdk':
        vmdk = archive
        ovf = False
    else:
        print("[+] Extracting files")
        patoolib.extract_archive(f"{archive}", outdir=temp_directory,verbosity=-1)
        print("[+] Extracted files.  Locating ovf and vmdk files")
        #We assume we only have one vmdk and one ovf file here.
        try:
            vmdk = find_files_with_extension(temp_directory,'vmdk')[0]
        except IndexError:
            print("[-] No vmdk file found.  Checking if there are more archive files.")
            #This is just looking for ova.  What if there is more rar, or 7z, or zip?
            new_archive_file = find_files_with_extension(temp_directory,'ova')[0]
            vmdk,ovf = extract_vm(new_archive_file,temp_directory)
        try:
            ovf = find_files_with_extension(temp_directory,'ovf')[0]
        except IndexError:
            print("[-] No ovf file found.")
            ovf = False
    # nested archive files?
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


def create_vm(virtual_disk_file,ovf,storage_location,vm_id,machine_name):
    ''' Create the VM using the ovf and vmdk files. '''
    print("[+] Creating VM")
    if ovf is not False:
        subprocess.run(f'qm importovf {vm_id} "{ovf}" {storage_location} --format qcow2',
                       shell=True, stdout=subprocess.DEVNULL,check=True)
        subprocess.run(f'qm set {vm_id} -name "{machine_name}"',
                       shell=True, stdout=subprocess.DEVNULL,check=True)
    else:
        subprocess.run(f'qm create {vm_id} --storage {storage_location} --memory 1024 --cores 1',
                       shell=True, stdout=subprocess.DEVNULL,check=True)
    print("[+] Created VM")
    print("[+] Loading virtual disk to VM")
    subprocess.run(f'qm importdisk {vm_id} "{virtual_disk_file}" {storage_location} --format qcow2',
                   shell=True, stdout=subprocess.DEVNULL,check=True)

def configure_vm(vm_id,storage,bridge,ovf):
    ''' Configure the VM, including the following steps
            attach the disk
            set the correct boot order
            set the network interface '''

    print("[+] Configuring VM.")
    if ovf is not False:
        subprocess.run(f'qm set {vm_id} -sata0 "{storage}:{vm_id}/vm-{vm_id}-disk-1.qcow2"',
                       shell=True, stdout=subprocess.DEVNULL,check=True)
    else:
        subprocess.run(f'qm set {vm_id} -sata0 "{storage}:{vm_id}/vm-{vm_id}-disk-0.qcow2"',
                       shell=True, stdout=subprocess.DEVNULL, check=True)
    subprocess.run(f'qm set {vm_id} -boot "order=sata0"',
                   shell=True, stdout=subprocess.DEVNULL,check=True)
    subprocess.run(f'qm set {vm_id} -net0 "model=virtio,bridge={bridge}"',
                   shell=True, stdout=subprocess.DEVNULL,check=True)

def clean_up(directory):
    ''' Clean up anything created by this script '''
    print("[+] Cleaning up downloaded files.")
    subprocess.run(f'rm -rf {directory}',shell=True,check=True)

def find_vmid():
    ''' Look at the current VMIDs and pick an available one '''

    vmid_list = subprocess.run("qm list | awk '{print $1}' | grep '^4.'",
                               shell=True,capture_output=True,text=True,
                               check=True).stdout.strip().split('\n')
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

args = get_arguments()

if not args.id:
    print("[!] No VMID provided.  Let me find one for you...")
    vmid = find_vmid()
    print(f"[!] {str(vmid)} has been selected.")
else:
    vmid = args.id
    check_vmid_available(vmid)

vm_name = args.url.split('/')[3]

with tempfile.TemporaryDirectory() as temp_dir:
    vm_archive = download_vm(args.url,temp_dir)
    ARCHIVE_FILE = f"{temp_dir}/{vm_archive}"
    vmdk_file,ovf_file = extract_vm(ARCHIVE_FILE,temp_dir)
    create_vm(vmdk_file,ovf_file,args.storage,vmid,vm_name)
    configure_vm(vmid,args.storage,args.network,ovf_file)
    clean_up(temp_dir)
    complete(vmid,vm_archive)
