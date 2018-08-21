#!/usr/bin/env python3

###############################################################################
#
#  Project:  MLontheEdgeCodeStory
#  File:     pisetup.py
#  Authors:  David (Seun) Odun-Ayo
#  Description: This script gets the latest version of the pi3 folder  and 
#   categories.txt from azure blob storage and then makes it for use on the 
#   project 
#  Requires: Python 3.x
#
###############################################################################

import logging
import os
import shutil
import sys
import zipfile
from azure.storage.blob import BlockBlobService, ContentSettings, PublicAccess

SCRIPT_DIR = os.path.split(os.path.realpath(__file__))[0]

def azure_download_from_path(model_container_name, model_dir_path, compressed_model_dir_path, compressed_model_name):
    # Define categories variables and get categories.txt
    categories_dir = "categories.txt"
    categories_path = "{0}/{1}".format(SCRIPT_DIR, categories_dir)
    block_blob_service.get_blob_to_path(model_container_name, categories_dir, categories_path)
        
    #Download Azure Version to the Raspberry pi
    block_blob_service.get_blob_to_path(model_container_name, compressed_model_name, compressed_model_dir_path)
    os.makedirs(model_dir_path)
    zf = zipfile.ZipFile(compressed_model_dir_path)
    zf.extractall(model_dir_path)
    os.remove(compressed_model_dir_path)



def main():
    # Define Globals
    global block_blob_service

    # Define Locals
    model_container_name = 'edgemodels'
    current_dir = os.getcwd()
    model_dir = "pi3"
    build_dir = "build"
    model_dir_path = "{0}/{1}".format(SCRIPT_DIR, model_dir)
    build_dir_path = "{0}/{1}".format(model_dir_path, build_dir)
    compressed_model_name = "zipped{0}".format(model_dir)
    compressed_model_dir_path ="{0}/{1}.zip".format(SCRIPT_DIR, compressed_model_name)

    # Intialize Log Properties
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s') 
   
    # Get Login Credentials
    azure_key_name = os.environ.get('AZURE_BLOBCONTAINER_NAME')
    azure_key = os.environ.get('AZURE_BLOBCONTAINER_KEY')

    if azure_key_name is None:
        logging.debug('Name Error Failed. Exiting....')
        sys.exit(1)

    if azure_key is None:
        logging.debug('Key Error Failed. Exiting....')
        sys.exit(1)

    if azure_key and azure_key_name is not None:
        logging.debug('Everything worked fine')

        
    # Set up Azure Credentials
    block_blob_service = BlockBlobService(account_name = azure_key_name, account_key = azure_key)
    if block_blob_service is None:
        logging.debug("No Azure Storage Account Connected")
        sys.exit(1)
    
    # Delete the current version on the Raspberry Pi if there is one
    if os.path.exists(model_dir_path):
        shutil.rmtree(model_dir_path)

    # Download Pi3 from Azure
    logging.debug('Downloading from Azure Blob Storage')
    azure_download_from_path(model_container_name, model_dir_path, compressed_model_dir_path, compressed_model_name)
    
    # Azure should catch this issue but still check one more time to make sure that the correct directory has been downloaded
    if os.path.exists(model_dir_path):
        os.chdir(model_dir_path)

    # Create a build Folder
    logging.debug('Creating Build Folder')
    while not os.path.exists(build_dir_path):
        os.makedirs(build_dir_path)
   
    # Change into the 'build' folder
    os.chdir(build_dir_path)
    
    logging.debug('Running make on Pi3 Building Folder')
    
    # Call the OS to run the 'cmake' command
    os.system('cmake .. -DCMAKE_BUILD_TYPE=Release')

    # Call the OS to run the essential 'make' command
    os.system('make')

    # Change back into our current scripts Directory
    os.chdir(current_dir)

if __name__ == '__main__':
    main()
