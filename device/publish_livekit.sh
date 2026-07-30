# device/publish_livekit.sh
#!/usr/bin/env bash
set -e

# Helper script to publish the Pi camera to LiveKit using GStreamer + webrtcbin.
# This script is a template. LiveKit WebRTC publishing from GStreamer requires
# a working webrtcbin pipeline and appropriate plugins (gst-plugins-good/bad/ugly, libwebrtc, etc.).
# Many systems do not ship a ready-to-run pipeline; this script prints the token and
# attempts to run gst-launch-1.0 if available. You will likely need to adapt the pipeline.

if [ -z "$LIVEKIT_URL" ] || [ -z "$LIVEKIT_TOKEN" ]; then
  echo "LIVEKIT_URL and LIVEKIT_TOKEN must be set in the environment"
  exit 1
fi

echo "LiveKit URL: $LIVEKIT_URL"
echo "LiveKit token: $LIVEKIT_TOKEN"

echo "This script is a template. Please adapt the GStreamer webrtcbin pipeline to your system."

echo "Example (pseudo) pipeline steps:"
echo "  - Create a webrtc PeerConnection to $LIVEKIT_URL using $LIVEKIT_TOKEN"
echo "  - Attach the camera source (v4l2src or libcamera) to webrtcbin as a video track"
echo "  - Set ICE servers if required"

echo "There is no universal gst-launch command provided here because the webrtcbin usage is interactive and
usually implemented with a small helper program that negotiates SDP and ICE. Consider using a LiveKit
example client, or building a small GStreamer application using gst-plugins and libwebrtc."

# If you have a helper binary called livekit-gst-publish that accepts URL and token, you could invoke it here:
if command -v livekit-gst-publish >/dev/null 2>&1; then
  echo "Found livekit-gst-publish, launching it..."
  exec livekit-gst-publish --url "$LIVEKIT_URL" --token "$LIVEKIT_TOKEN" "$@"
fi

# If gst-launch-1.0 is installed and you have a custom pipeline script, try running it
if command -v gst-launch-1.0 >/dev/null 2>&1; then
  echo "gst-launch-1.0 present but no sample webrtcbin pipeline provided. Exiting."
  exit 0
fi

echo "No publisher helper available. Install a LiveKit-aware publisher or adapt this script."
exit 2
