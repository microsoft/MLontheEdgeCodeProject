#!/usr/bin/env python3
###############################################################################
#
#  Project:  MLontheEdgeCodeStory
#  File:     Host.py
#  Authors:  David (Seun) Odun-Ayo
#  Description: User runs this on there host computer to transfer pi3 folder
#   and its corresponding categories.txt to Azure Blob Storage 
#  Requires: Python 3.x
#
###############################################################################

import json
import os
import shutil
import sys
import time
import zipfile
from datetime import datetime, timedelta
from azure.storage.blob import BlockBlobService, ContentSettings, PublicAccess

SCRIPT_DIR = os.path.split(os.path.realpath(__file__))[0]

def main():
    # Define Globals
    global block_blob_service
    
    # Define categories variables
    categories_dir = "categories.txt"
    categories_path = "{0}/{1}".format(SCRIPT_DIR, categories_dir)
    
    # Define model variables
    model_dir = "pi3"
    model_dir_path = "{0}/{1}".format(SCRIPT_DIR, model_dir)
    compressed_model_name = "zipped{0}".format(model_dir)
    model_container_name = 'edgemodels'
    compressed_model_dir_path ="{0}/{1}.zip".format(SCRIPT_DIR, compressed_model_name)
    
     # Intialize Azure Properties
    azure_key_name = os.environ.get('AZURE_BLOBCONTAINER_NAME')
    azure_key = os.environ.get('AZURE_BLOBCONTAINER_KEY')

    if azure_key_name is None:
        print('Name Error Failed. Exiting....')
        sys.exit(1)

    if azure_key is None:
        print('Key Error Failed. Exiting....')
        sys.exit(1)

    if azure_key and azure_key_name is not None:
        print('Everything worked fine')

    block_blob_service = BlockBlobService(account_name = azure_key_name, account_key = azure_key)
    
    # Create Blob Container if it doesn't already exists
    block_blob_service.create_container(model_container_name)

    # Compress the current model file on the computer
    if os.path.exists(model_dir_path):
        shutil.make_archive(compressed_model_name, 'zip', model_dir_path)
    else:
        print("There is no model file in this directory")
        sys.exit(1)

    # Upload the Compressed Model File to Azure
    block_blob_service.create_blob_from_path(model_container_name, compressed_model_name, compressed_model_dir_path, content_settings=ContentSettings(content_type='application/zip'))

    # Upload the categories.txt for your specific model to Azure
    if os.path.exists(categories_path):
        block_blob_service.create_blob_from_path(model_container_name, categories_dir, categories_path)
    else:
        print("There is no categories.txt file on this Device")
        sys.exit(1)

    # Upload Categories File to Azure

if __name__ == '__main__':
    main()
