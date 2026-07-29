# device/signal_publisher.py
"""Direct WebRTC signaling publisher using IVY /signal. Uses aiortc to create a PeerConnection and answer viewer offers.
This implementation listens on a simple local websocket for incoming 'viewer_offer' messages forwarded by the IVY /signal upgrade.
The IVY device WebSocket client will receive 'viewer_offer' messages and should call publisher.handle_viewer_offer.
"""
import asyncio
import os
import json
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaBlackhole

# We export a simple class the DeviceClient can call when a viewer_offer arrives
class SignalPublisher:
    def __init__(self, picam_track):
        self.picam_track = picam_track
        self.pcs = set()

    async def handle_viewer_offer(self, offer_sdp, offer_type='offer'):
        pc = RTCPeerConnection()
        self.pcs.add(pc)
        @pc.on('connectionstatechange')
        def on_connstate():
            print('Connection state', pc.connectionState)
            if pc.connectionState == 'failed' or pc.connectionState == 'closed':
                asyncio.ensure_future(pc.close())
                self.pcs.discard(pc)
        # attach our camera track
        class TrackWrapper(MediaStreamTrack):
            kind = 'video'
            def __init__(self, track):
                super().__init__()
                self.track = track
            async def recv(self):
                return await self.track.recv()
        video_track = TrackWrapper(self.picam_track)
        pc.addTrack(video_track)
        # handle offer/answer
        offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return pc.localDescription.sdp

    async def close(self):
        coros = [pc.close() for pc in list(self.pcs)]
        await asyncio.gather(*coros)
