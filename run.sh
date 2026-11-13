#!/bin/bash
# Launch KinectCam (libfreenect's USB chatter goes to kinectcam.log)
cd "$(dirname "$0")"
exec .venv/bin/python -u kinectcam.py "$@" 2> >(grep -v -E "Invalid magic|Lost [0-9]+|write_register|Negotiated packet" >&2)
