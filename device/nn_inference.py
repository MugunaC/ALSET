# device/nn_inference.py
"""
NN inference service for ALSET.
- Loads a quantized MobileNetV2 model artifact (preferred formats: ONNX quantized or TorchScript quantized).
- Exposes `enqueue_frame(frame, meta)` to receive frames (numpy BGR or PIL).
- Outputs actions via provided action_cb(action_dict, meta) callback which should be safe-checked by the caller.

This is inference-only. Training hooks are intentionally omitted on-device.
"""

import time
import threading
import queue
import numpy as np
from PIL import Image
import io
import os

# Try to import ONNX Runtime first (faster on Pi with proper build)
try:
    import onnxruntime as ort
    _HAS_ORT = True
except Exception:
    _HAS_ORT = False

try:
    import torch
    _HAS_TORCH = True
except Exception:
    _HAS_TORCH = False

class NNInferenceService:
    def __init__(self, model_path, action_cb, input_size=(224,224), max_queue=2, prefer_onnx=True):
        """
        model_path: path to .onnx or .pt (torchscript)
        action_cb: function(action_dict, meta) -> called for each inferred action
        """
        self.model_path = model_path
        self.input_size = input_size
        self.action_cb = action_cb
        self.q = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        # backend chooser
        self.backend = None
        if _HAS_ORT and model_path.lower().endswith('.onnx') and prefer_onnx:
            try:
                self.ort_sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
                self.backend = 'onnx'
            except Exception:
                self.ort_sess = None
        if self.backend is None and _HAS_TORCH and model_path.lower().endswith('.pt'):
            try:
                self.torch_mod = torch.jit.load(model_path, map_location='cpu')
                self.torch_mod.eval()
                self.backend = 'torch'
            except Exception:
                self.torch_mod = None
        if self.backend is None:
            raise RuntimeError("No supported backend available for model: " + model_path)
        self._thread.start()

    def enqueue_frame(self, frame, meta=None):
        """
        frame: numpy array BGR or PIL.Image - will be converted to RGB and resized
        meta: optional dict
        """
        try:
            self.q.put_nowait((frame, meta))
            return True
        except queue.Full:
            # drop frames under overload
            return False

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def _preprocess(self, frame):
        # convert to PIL Image RGB
        if isinstance(frame, np.ndarray):
            # assume BGR from cv2
            img = Image.fromarray(frame[..., ::-1])
        elif isinstance(frame, Image.Image):
            img = frame
        else:
            # assume bytes
            img = Image.open(io.BytesIO(frame)).convert('RGB')
        img = img.resize(self.input_size)
        # normalize to float32 0..1 then std/mean as mobilenet expects
        arr = np.array(img).astype('float32') / 255.0
        # transpose to CHW
        arr = np.transpose(arr, (2,0,1))
        # normalize using ImageNet mean/std
        mean = np.array([0.485, 0.456, 0.406], dtype='float32')[:,None,None]
        std = np.array([0.229, 0.224, 0.225], dtype='float32')[:,None,None]
        arr = (arr - mean) / std
        # add batch dim
        arr = np.expand_dims(arr, 0).astype('float32')
        return arr

    def _postprocess_to_action(self, model_output):
        """
        Convert model output to the action dict your robot uses.
        Default: treat model as a small classifier mapping to discrete actions.
        Customize mapping in your application.
        """
        if isinstance(model_output, np.ndarray):
            probs = model_output.squeeze()
        elif isinstance(model_output, list):
            probs = np.array(model_output[0]).squeeze()
        else:
            probs = np.array(model_output)
        action_idx = int(np.argmax(probs))
        mapping = ['FORWARD','LEFT','RIGHT','STOP']
        action_name = mapping[action_idx] if action_idx < len(mapping) else 'STOP'
        return {'action': action_name, 'score': float(probs[action_idx])}

    def _infer_onnx(self, inp):
        input_name = self.ort_sess.get_inputs()[0].name
        out = self.ort_sess.run(None, {input_name: inp})
        return out[0]

    def _infer_torch(self, inp):
        import torch
        t = torch.from_numpy(inp)
        with torch.no_grad():
            out = self.torch_mod(t)
            if isinstance(out, torch.Tensor):
                return out.cpu().numpy()
            elif isinstance(out, (tuple, list)):
                return out[0].cpu().numpy()
            else:
                return np.array(out)

    def _worker(self):
        while not self._stop.is_set():
            try:
                frame, meta = self.q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                inp = self._preprocess(frame)
                if self.backend == 'onnx':
                    out = self._infer_onnx(inp)
                else:
                    out = self._infer_torch(inp)
                action = self._postprocess_to_action(out)
                try:
                    self.action_cb(action, meta)
                except Exception:
                    pass
            except Exception:
                import traceback; traceback.print_exc()