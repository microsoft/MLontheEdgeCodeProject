#!/usr/bin/env python3

import cv2
import ellmanager as emanager
import io
import json
import logging
import model
import numpy as numpy
import os
import picamera
import random
import shutil
import subprocess
import sys
import termios
import time
import tty
import zipfile
from datetime import datetime, timedelta
from azure.storage.blob import BlockBlobService, ContentSettings, PublicAccess
from iothub_client import IoTHubClient, IoTHubClientError, IoTHubTransportProvider, IoTHubClientResult, IoTHubError, DeviceMethodReturnValue
from iothub_service_client import IoTHubRegistryManager, IoTHubRegistryManagerAuthMethod
from iothub_service_client import IoTHubDeviceTwin, IoTHubError
SCRIPT_DIR = os.path.split(os.path.realpath(__file__))[0]

CONNECTION_STRING = ""
PROTOCOL = IoTHubTransportProvider.MQTT
CLIENT = IoTHubClient(CONNECTION_STRING, PROTOCOL)
SEND_REPORTED_STATE_CONTEXT = 0
METHOD_CONTEXT = 0
SEND_REPORTED_STATE_CALLBACKS = 0
METHOD_CALLBACKS = 0

class PiImageDetection():
    
    def __init__(self):
        # Intialize Azure Blob Container Properties
        self.picture_container_name = 'edgeimages'
        self.video_container_name = 'edgevideos'
        self.model_container_name = 'edgemodels'
        self.json_container_name = 'edgejson'

        # Intialize Azure IoTHub Config Properties
        self.capture_rate = 30.0
        self.prediction_threshold = 0.4
        self.camera_res_len = 256
        self.camera_res_wid = 256
        self.video_capture_length = 30
        self.video_preroll = 5
        self.capture_video = False

        azure_key_name = os.environ.get('AZURE_BLOBCONTAINER_NAME')
        azure_key = os.environ.get('AZURE_BLOBCONTAINER_KEY')

        if azure_key_name is None:
            logging.debug('Name Error Failed. Exiting....')
            sys.exit(1)

        if azure_key is None:
            logging.debug('Key Error Failed. Exiting....')
            sys.exit(1)

        self.block_blob_service = BlockBlobService(account_name = azure_key_name, account_key = azure_key)

        
    def run_shell(self, cmd):
        """
        Used for running shell commands
        """
        output = subprocess.check_output(cmd.split(' '))
        logging.debug('Running shell command')
        if output is None:
            logging.debug('Error Running Shell Command. Exiting...')
            sys.exit(1)
        return str(output.rstrip().decode())

    def save_video(self, input_path, output_path, rename_path):
        # Convert each indivudul .h264 to mp4 
        mp4_box = "MP4Box -fps {0} -quiet -add {1} {2}".format(self.capture_rate, input_path, output_path)
        # Call the OS to perform the compressing
        self.run_shell(mp4_box)
        # Remove the .h264 file to save space on the RPI
        os.remove(input_path)
        # Rename for Better Convention Understanding
        os.rename(output_path, rename_path)
        logging.debug('Video Saved')

    def model_predict(self, image):
        # Open the required categories.txt file used for identify the labels for recognized images
        with open("categories.txt", "r") as cat_file:
            categories = cat_file.read().splitlines()

        # Determine the right size and shape that the model wants
        input_shape = model.get_default_input_shape()
        # Get the given image ready for use with the model
        input_data = emanager.prepare_image_for_model(image, input_shape.columns, input_shape.rows)
        # Make the Model Prediction
        prediction = model.predict(input_data)
        # Return the max top 2 predictions if they exits
        top_2 = emanager.get_top_n(prediction, 2)
        # Make a decision on what to do based on the return prediction values
        if (len(top_2) < 1):
            # If nothing, return nothing
            return None, None
        else:
            # Something was recongized, give the name based on the categories file and give the value
            word = categories[top_2[0][0]]
            predict_value = top_2[0][1]
            return word, predict_value

    def write_json_to_file(self, video_time, word_prediction, predicition_value, video_name, json_path):
        # Template for description of the image and video taken
        json_message = {
            'Description': {
                'sysTime':               str(datetime.now().isoformat()) + 'Z',
                'videoStartTime':        str(video_time.isoformat()) + 'Z',
                'prediction(s)':         word_prediction,
                'predictionConfidence':  str(predicition_value),
                'videoName':             video_name
            }
        }
        logging.debug("Rewriting Json to File")
        # Write Json Message to file
        with open(json_path, 'w') as json_file:
            json.dump(json_message, json_file)

    def azure_model_update(self, update_json_path): 
        # List the Models in the blob. There should only be one named zippedpi3
        model_blob_list = self.block_blob_service.list_blobs(self.model_container_name)
        found_blob = False
        for blob in model_blob_list:
            # Find the given one if there are more than one models
            if (blob.name == 'zippedpi3'):
                # Get the Date of the most recent update
                last_blob_update = str(blob.properties.last_modified)
                # Leave the loop once we found what we want
                found_blob = True
                break
        # Check to make sure that there is a catch for if there is no zippedpi3 folder on Azure
        if found_blob == False:
            logging.debug("No Pi3 was found on Azure. Re-run pi3setup.py and make sure your Azure Blob Storage Account is up to date")
        
        # If we don't already got the json just go ahead and create a new one
        if not os.path.exists(update_json_path) or os.stat(update_json_path).st_size == 0:
            # Since we did not have the json of infomation about it, go ahead and update to be safe
            os.system('python3 pisetup.py')
            # Save the timestamp of the last time things were updated
            holder = {"lastupdate": last_blob_update}
            # After updating, make sure we know update the json
            with open(update_json_path, "w+") as f:
                f.write(json.dumps(holder))

        # Now that we need know we have it, we need to parse it and decide if we need to update or not
        with open(update_json_path, "r") as j:
            json_data = json.load(j)
            last_model_update = json_data["lastupdate"]

        # If the times are not equal and there has been a change somewhere Update
        if (last_model_update != last_blob_update):
            # Check to make sure that we have the pisetup.py script
            print ('They were not the same so I will be performing an update now')
            os.system('python3 pisetup.py')
            
            # Change the json file to represent the new modified time
            json_data["lastupdate"] = last_blob_update
            with open (update_json_path, "w+") as j:
                json.dump(json_data, j)

    def iothub_client_init(self):
        if CLIENT.protocol == IoTHubTransportProvider.MQTT or client.protocol == IoTHubTransportProvider.MQTT_WS:
            CLIENT.set_device_method_callback(self.device_method_callback, METHOD_CONTEXT)

    def send_reported_state_callback(self, status_code, user_context):
        global SEND_REPORTED_STATE_CALLBACKS
        print ( "Device twins updated." )

    def device_method_callback(self, method_name, payload, user_context):
        global METHOD_CALLBACKS

        if method_name == "DeviceConfig":
            logging.debug( "Waiting for Configuration..." )
            if payload is not None:
                print ("Payload Received: {0}".format(payload))
                # Parse the Payload right here
                configuration = json.loads(payload)
                for key, value in dict.items(configuration):
                    print("Key and Value from Azure: {0} and {1}".format(key, value))
                    if isinstance(value, str):
                        if key == "predictionThreshold":
                            self.prediction_threshold = float(value)
                        elif key == "captureRate":
                            self.capture_rate = value
                        elif key == "cameraResolutionLength":
                            self.camera_res_len = value
                        elif key == "cameraResolutionWidth":
                            self.camera_res_wid = value
                        elif key == "captureLength":
                            self.video_capture_length = value
                        elif key == "capturePreroll":
                            self.video_preroll = value
                    elif isinstance(value, bool):
                        if key == "captureVideo":
                            self.capture_video = value
                    else:
                        logging.debug("The value was a string")
                    
                    
            current_time = str(datetime.now().isoformat())
            reported_state = "{\"rebootTime\":\"" + current_time + "\"}"
            CLIENT.send_reported_state(reported_state, len(reported_state), self.send_reported_state_callback, SEND_REPORTED_STATE_CONTEXT)
        else:
            print("Another Method was called")

        # Azure IoT Hub Response
        device_method_return_value = DeviceMethodReturnValue()
        device_method_return_value.response = "{ \"Response\": \"Successful Config\" }"
        device_method_return_value.status = 200

        return device_method_return_value
    
    # Function to Upload a specified path to an object to Azure Blob Storage
    def azure_upload_from_path(self,blob_container,blob_name,blob_object,blob_format):
        self.block_blob_service.create_blob_from_path(blob_container, blob_name,blob_object, content_settings=ContentSettings(content_type=blob_format))

    def get_video(self):
        # Define Variables
        capture_time = self.video_capture_length
        preroll = self.video_preroll
        capture_video = self.capture_video
        camera_res = (self.camera_res_len, self.camera_res_wid)
        image = numpy.empty((camera_res[1], camera_res[0],3), dtype=numpy.uint8)
        capture_counter = 0

        # Set up Circular Buffer Settings
        video_stream = picamera.PiCameraCircularIO(camera_device, seconds=capture_time)
        camera_device.start_preview()
        camera_device.start_recording(video_stream, format='h264')
        my_now = datetime.now()

        while True:
            if capture_counter < 8:
                # Set up a waiting time difference
                my_later = datetime.now()
                difference = my_later-my_now
                seconds_past = difference.seconds
                camera_device.wait_recording(1)

                logging.debug('Analyzing Surroundings')
                if seconds_past > preroll+1:
                    # Take Picture for the Model
                    camera_device.capture(image,'bgr', resize=camera_res, use_video_port=True)
                    camera_device.wait_recording(1)
                    
                    # Take Picture for Azure
                    image_name = "image-{0}.jpg".format(my_later.strftime("%Y%m%d%H%M%S"))
                    image_path = "{0}/{1}".format(SCRIPT_DIR, image_name)
                    camera_device.capture(image_path)
                    camera_device.wait_recording(1)

                    print("Prediction Threshold: {}".format(self.prediction_threshold))
                    # Make Prediction with the first picture
                    logging.debug('Prediction Captured')
                    word, predict_value = self.model_predict(image)
                    
                    # Give time here for model predictions
                    camera_device.wait_recording(3)
                    logging.debug('Prediction Returned')
                    my_now = datetime.now()
                    
                    if word is None:
                        logging.debug('No Event Registered')
                        capture_video = False
                        # Format specifically for the Good Folder
                        bad_image_folder = "{0}/badimages".format(self.picture_container_name)
                        # Send Picture to the Bad Images Folder on Azure that can be used to retrain
                        self.azure_upload_from_path(bad_image_folder, image_name, image_path, 'image/jpeg')
                    elif word is not None and predict_value < self.prediction_threshold:
                        logging.debug('Prediction Value Too Low')
                        capture_video = False
                        # Format Specifically for the Good FOlder
                        bad_image_folder = "{0}/badimages".format(self.picture_container_name)
                        # Send Picture to the Bad Images Folder on Azure that can be used to retrain
                        self.azure_upload_from_path(bad_image_folder, image_name, image_path, 'image/jpeg')
                        camera_device.wait_recording(2)
                    else:
                        # See what we got back from the model
                        logging.debug('Event Registered')
                        capture_video=True
                        print('Prediction(s): {}'.format(word))
                        # Format specifically for the Good Folder
                        good_image_folder = "{0}/goodimages".format(self.picture_container_name)
                        # Send the Picture to the Good Images Folder on Azure
                        self.azure_upload_from_path(good_image_folder, image_name, image_path, 'image/jpeg')
                        camera_device.wait_recording(2)
                        # Once it is uploaded, delete the image
                        os.remove(image_path)
                        break
                    # If we don;t break by finidng the right predicition stay in the loop
                    seconds_past = 0
                    capture_counter = capture_counter + 1
                    # Delete the image from the OS folder to save space
                    os.remove(image_path)
            else:
                camera_device.stop_recording()
                return

        ## Create diretory to save the video that we get if we are told to capture video
        start_time = my_later
        base_dir = SCRIPT_DIR
        video_dir = "myvideos"
        video_dir_path ="{0}/{1}".format(base_dir, video_dir)

        if not os.path.exists(video_dir_path):
            os.makedirs(video_dir_path)

        video_start_time = start_time - timedelta(seconds=preroll)

        ## We will have two seperate files, one for before and after the event had been triggered
        #Before:
        before_event =         "video-{0}-{1}.h264".format("before", video_start_time.strftime("%Y%m%d%H%M%S"))
        before_event_path =    "{0}/{1}/{2}".format(base_dir, video_dir, before_event)
        before_mp4 =           before_event.replace('.h264', '.mp4')
        before_mp4_path =      "{0}/{1}/{2}".format(base_dir, video_dir, before_mp4)
        before_path_temp =      "{0}.tmp".format(before_mp4_path)

        # After:
        after_event =         "video-{0}-{1}.h264".format("after", video_start_time.strftime("%Y%m%d%H%M%S"))
        after_event_path =    "{0}/{1}/{2}".format(base_dir, video_dir, after_event)
        after_mp4 =           after_event.replace('.h264', '.mp4')
        after_mp4_path =      "{0}/{1}/{2}".format(base_dir, video_dir, after_mp4)
        after_path_temp =     "{0}.tmp".format(after_mp4_path)

        # Full combined video path
        full_path =           "video-{0}-{1}.mp4".format("full", video_start_time.strftime("%Y%m%d%H%M%S"))
        full_video_path =     "{0}/{1}/{2}".format(base_dir, video_dir, full_path)

        # Create a json file to a reference the given event
        json_file_name = "video-description-{0}.json".format(video_start_time.strftime("%Y%m%d%H%M%S"))
        json_file_path = "{0}/{1}/{2}".format(base_dir,video_dir, json_file_name)

        if capture_video == True:
            # Save the video to a file path specified
            camera_device.split_recording(after_event_path)
            video_stream.copy_to(before_event_path, seconds=preroll)
            camera_device.wait_recording(preroll+5)
                    
            # Convert to MP4 format for viewing
            self.save_video(before_event_path, before_path_temp, before_mp4_path)
            self.save_video(after_event_path, after_path_temp, after_mp4_path)

            # Upload Before Videos to Azure Blob Storage
            before_video_folder = "{0}/{1}".format(self.video_container_name, 'beforevideo')
            self.azure_upload_from_path(before_video_folder, before_mp4, before_mp4_path, 'video/mp4')

            # Upload After Videos to Azure Blob Storage
            after_video_folder = "{0}/{1}".format(self.video_container_name, 'aftervideo')
            self.azure_upload_from_path(after_video_folder, after_mp4, after_mp4_path, 'video/mp4')

            # Combine the two mp4 videos into one and save it
            full_video = "MP4Box -cat {0} -cat {1} -new {2}".format(before_mp4_path, after_mp4_path, full_video_path)
            self.run_shell(full_video)
            logging.debug('Combining Full Video')
            
            # Upload Video to Azure Blob Storage
            full_video_folder = "{0}/{1}".format(self.video_container_name, 'fullvideo')
            self.azure_upload_from_path(full_video_folder, full_path, full_video_path, 'video/mp4')

            # Create json and fill it with information
            self.write_json_to_file(video_start_time, word, predict_value, full_path, json_file_path)

            # Upload Json to Azure Blob Storge
            self.azure_upload_from_path(self.json_container_name, json_file_name, json_file_path, 'application/json')
        
            # End Things
            shutil.rmtree(video_dir_path)
            camera_device.stop_recording()

    def main(self):
        # Define Globals
        global camera_device

        # Intialize Log Properties
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s') 

        # Intilize Camera properties 
        camera_device = picamera.PiCamera()
        camera_device.resolution = (1280, 720)
        camera_device.framerate = self.capture_rate
        
        if camera_device is None:
            logging.debug("No Camera Device Found.")
            sys.exit(1)

        # Create Neccesary Containers and Blobs if they don't exist already
        self.block_blob_service.create_container(self.picture_container_name)
        self.block_blob_service.create_container(self.video_container_name)
        self.block_blob_service.create_container(self.model_container_name)
        self.block_blob_service.create_container(self.json_container_name)
                
        # Intialize the updates Json File
        update_json_path = "{0}/{1}.json".format(SCRIPT_DIR, 'updatehistory')
        
        # Intialize IoTHub
        try:
            self.iothub_client_init()
            # Constantly run the Edge.py Script
            while True:
                logging.debug('Starting Edge.py')

                # Check and Run Model Updates
                self.azure_model_update(update_json_path)
                
                # Began running and stay running the entire project.
                self.get_video()
        except IoTHubError as iothub_error:
            print ( "Unexpected error %s from IoTHub" % iothub_error )
            return
    

if __name__ == '__main__':
    mydetector = PiImageDetection()
    mydetector.main()
