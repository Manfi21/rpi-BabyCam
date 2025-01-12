# Raspberry Pi BabyCam

![](.assets/rpi_babyCam_front.jpg)

# Installation
## Raspberry Pi:
- Install the latest Pi OS lite 64bit and go to Advanced Settings
  - Setup home Wifi
  - Setup Hostname `PiCam`
- Connect via shh
- Switch to root
```
sudo su
```
- Update the Pi
```
sudo apt update && apt upgrade -y
```

## Install MediaMTX :
MediaMTX will now be downloaded. Which version you use depends on Raspbian version and Pi used
- Get Raspian version 
```
uname -m
```
- Visit https://github.com/bluenviron/mediamtx/releases for latest versions and download links.
- Copy the link and enter in the terminal with wget prefix, below example I’m using the latest (v1.9.0) 64bit version
```
wget https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_linux_arm64v8.tar.gz
```
- Extract the files
```
tar xzvf mediamtx_v1.9.0_linux_arm64v8.tar.tar.gz
```
### MediaMTX config
**If you want to add Audio to the Stream please follow [Install Audio](#install-mediamtx-audio).**
- Edit the yml file so it uses the Pi camera
```
nano mediamtx.yml
```
- Scroll to the bottom of the file, replace the following lines of code at the end of the file. 
```
paths:
  # example:
  # my_camera:
  #   source: rtsp://my_camera
  # Settings under path "all_others" are applied to all paths that
  # do not match another entry.
  all_others: 
```
- With the following:
```
paths:
  cam:
    source: rpiCamera
    sourceOnDemand: true

  cam_with_audio:
    runOnDemand: >
      gst-launch-1.0
      rtspclientsink name=s location=rtsp://localhost:$RTSP_PORT/cam_with_audio
      rtspsrc location=rtsp://127.0.0.1:$RTSP_PORT/cam latency=0 ! rtph264depay ! s.
      alsasrc device=hw:0 ! opusenc bitrate=16000 ! s.
    runOnDemandRestart: yes

  all_others:
```
- enable audio by replacing `hw:0` with your corresponding audio source.
```
alsasrc device=default:CARD=Mic ! opusenc bitrate=16000 ! s.
```

- The cam is now only running is someone is requesting the stream.
- additional config parameter: https://github.com/bluenviron/mediamtx/blob/main/mediamtx.yml starting at line [509](https://github.com/bluenviron/mediamtx/blob/df9f0f8cdb0e40344e11de9685e13da697a40f57/mediamtx.yml#L509)
### Example 
  ```
  # Flip horizontally
  rpiCameraHFlip: false
  ...
  # Enables printing text on each frame.
  rpiCameraTextOverlayEnable: true
  # Text that is printed on each frame.
  # format is the one of the strftime() function.
  rpiCameraTextOverlay: '%Y-%m-%d %H:%M:%S - BabyCam'
  ```
- The stream now shows the current time.
- Save and Exit.

### Add a service:
To allow it to start automatically and for easier control of the video feed, the program can be created as service. 
```
sudo mkdir /opt/mediamtx
sudo cp mediamtx /opt/mediamtx/
sudo cp mediamtx.yml /opt/mediamtx/
```
- Remove the temp files
```
rm mediamtx
rm mediamtx.yml
rm mediamtx_v1.9.0_linux_arm64v8.tar.tar.gz
```
- Create a new service file 
```
sudo nano /etc/systemd/system/mediamtx.service
```
- Paste the following: 
```
[Unit] 
Wants=network.target
[Service] 
ExecStart=/opt/mediamtx/mediamtx /opt/mediamtx/mediamtx.yml
[Install] 
WantedBy=multi-user.target
```
- Save and Exit.
- Reload systemctl 
```
sudo systemctl daemon-reload
```
- Start the service and enable at the same time
```
sudo systemctl enable --now mediamtx
```
- To check its running 
```
sudo systemctl status mediamtx
```

### Stream URL
Local access only!

Video only:
```
VLC -> rtsp://{RPI IP-Address}:8554/cam
WebRTC -> http://{RPI IP-Address}:8889/cam
HLS -> http://{RPI IP-Address}:8888/cam
```
Video and Audio:
```
VLC -> rtsp://{RPI IP-Address}:8554/cam_with_audio
WebRTC -> http://{RPI IP-Address}:8889/cam_with_audio
HLS -> http://{RPI IP-Address}:8888/cam_with_audio
```
You can also use the Pi hostname `PiCam.local` instead of IP Adress.

## Install MediaMTX Audio:
In order to add audio from a USB microfone, install GStreamer and alsa-utils:
```
sudo apt install -y gstreamer1.0-tools gstreamer1.0-rtsp gstreamer1.0-alsa alsa-utils
```
List available audio cards with:
```
arecord -L
```
Example output:
```
null
    Discard all samples (playback) or generate zero samples (capture)
hw:CARD=Mic,DEV=0
    Samson Go Mic, USB Audio
    Direct hardware device without any conversions
plughw:CARD=Mic,DEV=0
    Samson Go Mic, USB Audio
    Hardware device with all software conversions
default:CARD=Mic
    Samson Go Mic, USB Audio
    Default Audio Device
sysdefault:CARD=Mic
    Samson Go Mic, USB Audio
    Default Audio Device
front:CARD=Mic,DEV=0
    Samson Go Mic, USB Audio
    Front output / input
dsnoop:CARD=Mic,DEV=0
    Samson Go Mic, USB Audio
    Direct sample snooping device
```
- Look for the entry `default:`. In this example, `plughw:` also works well.
- Note the device name `default:CARD=Mic`.
- After you got the device instance continue with [Mediamtx config](#mediamtx-config).

## Install BLE WiFi Setup
We're using [Rpi-SetWiFi-viaBluetooth - Version 2](https://github.com/nksan/Rpi-SetWiFi-viaBluetooth/tree/main?tab=readme-ov-file).

```
curl  -L https://raw.githubusercontent.com/nksan/Rpi-SetWiFi-viaBluetooth/main/btwifisetInstall.sh | bash
```

Keep all Settings default. You can add a password if needed.

To check the Status of the new service:
```
systemctl status btwifiset
```

You can now use the Wifi settings in the new App (Version >= v1.5.4)

## Setup Tailscale:
With Tailscale remote access is easy to setup.

Install with one command:
```
curl -fsSL https://tailscale.com/install.sh | sh
```
- After Installation complete
```
tailscale up
```
- Visit the shown URL to login to your tailscale account
- Connect your device
- go to https://login.tailscale.com/admin/machines to see a list of all devices

## Setup Auto Wifi Access Point
- TBD

# Setup Android APP:

- Visit [App](App) to find the latest .apk
- Install the .apk
- Click the blue button in the top right corner to open the menu an click settings icon
- Enter the Local and if setup Remote IP without prot and suffx
- Enter the port and suffix below (WebRTC recommended for low latency) (e.g. 8889/cam)
- click `Save`
- By clicking the blue button you can choose the right URL type

### WiFi Settings
- Click on found BLE device in the list.
- After **sucessfull** connection you can `Get IP` or `Set Wifi`

### SSH connection
- the app will try both IPs for an SSH connection.
- Just click on `Auto Connect` and enter the credentials.
- after that you can `Reboot` `Shutdown` and send a `Custom command` with visual response.

# 3D printed Housing

Customized parts can be found [here](3D_files).\
Gopro style mounting extension can be found on [Thingiverse](https://www.thingiverse.com/thing:2584426).
